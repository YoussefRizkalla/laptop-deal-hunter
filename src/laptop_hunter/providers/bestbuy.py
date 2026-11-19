"""Best Buy official Products & Open-Box API provider."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx

from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.providers.base import BaseProvider

_RAM_VAL_RE = re.compile(r"(\d{1,3})\s*gigabyte|(\d{1,3})\s*gb", re.I)
_SSD_VAL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(tb|terabyte|gb|gigabyte)", re.I)


def _extract_detail_specs(details: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Extract structured RAM/SSD/GPU/Screen hints from Best Buy product details."""
    specs: dict[str, Any] = {}
    for item in details or []:
        name = str(item.get("name") or "").lower()
        value = str(item.get("value") or "").strip()
        if not value:
            continue

        if "system memory (ram)" in name and "ram_gb" not in specs:
            m = _RAM_VAL_RE.search(value)
            if m:
                specs["ram_gb"] = int(m.group(1) or m.group(2))
        elif ("total storage capacity" in name or "solid state drive capacity" in name) and "ssd_gb" not in specs:
            m = _SSD_VAL_RE.search(value)
            if m:
                num = float(m.group(1))
                unit = m.group(2).lower()
                specs["ssd_gb"] = int(round(num * 1000)) if unit.startswith("t") else int(round(num))
        elif "screen size" in name and "screen_inches" not in specs:
            m = re.search(r"(\d{2}(?:\.\d)?)", value)
            if m:
                specs["screen_inches"] = float(m.group(1))
        elif "refresh rate" in name and "refresh_hz" not in specs:
            m = re.search(r"(\d{2,3})", value)
            if m:
                specs["refresh_hz"] = int(m.group(1))
        elif "display type" in name and "panel_type" not in specs:
            if "oled" in value.lower():
                specs["panel_type"] = "OLED"
            elif "mini-led" in value.lower() or "mini led" in value.lower():
                specs["panel_type"] = "Mini-LED"
            elif "ips" in value.lower():
                specs["panel_type"] = "IPS"
    return specs


def parse_bestbuy_products(payload: dict[str, Any]) -> list[RawListing]:
    """Convert Best Buy Products API JSON payload into RawListings."""
    listings: list[RawListing] = []
    for product in (payload or {}).get("products") or []:
        sku = str(product.get("sku") or "").strip()
        name = (product.get("name") or "").strip()
        url = (product.get("url") or "").strip()
        if not sku or not name or not url:
            continue

        sale_price = product.get("salePrice")
        regular_price = product.get("regularPrice")
        raw_specs = _extract_detail_specs(product.get("details"))
        if product.get("manufacturer"):
            raw_specs.setdefault("brand", str(product["manufacturer"]).strip())

        desc = " ".join(
            part for part in [product.get("shortDescription"), product.get("longDescription")] if part
        )

        listings.append(
            RawListing(
                provider="bestbuy",
                external_id=f"bb:{sku}",
                title=name,
                url=url,
                price_usd=float(sale_price) if sale_price is not None else None,
                msrp_usd=float(regular_price) if regular_price is not None else None,
                store="Best Buy",
                description=desc[:1200],
                image_url=product.get("image"),
                condition_hint=str(product.get("condition") or "new"),
                sku=sku,
                raw_specs=raw_specs,
            )
        )
    return listings


def parse_bestbuy_open_box(
    payload: dict[str, Any],
    base_by_sku: dict[str, RawListing],
) -> list[RawListing]:
    """Convert Best Buy Open-Box beta API payload into RawListings linked to base SKUs."""
    listings: list[RawListing] = []
    for entry in (payload or {}).get("results") or []:
        sku = str(entry.get("sku") or "").strip()
        base = base_by_sku.get(sku)
        if not base:
            continue
        for offer in entry.get("offers") or []:
            condition_label = str(offer.get("condition") or "Open-Box").strip()
            prices = offer.get("prices") or {}
            current_price = prices.get("current")
            regular_price = prices.get("regular") or base.msrp_usd
            if current_price is None:
                continue

            listings.append(
                RawListing(
                    provider="bestbuy",
                    external_id=f"bb:{sku}:openbox:{condition_label.lower()}",
                    title=f"[Open-Box {condition_label}] {base.title}",
                    url=base.url,
                    price_usd=float(current_price),
                    msrp_usd=float(regular_price) if regular_price is not None else None,
                    store="Best Buy",
                    description=base.description,
                    image_url=base.image_url,
                    condition_hint=f"open_box {condition_label}",
                    sku=sku,
                    raw_specs=dict(base.raw_specs),
                )
            )
    return listings


class BestBuyProvider(BaseProvider):
    """Fetch new and open-box gaming laptops from Best Buy's official API."""

    name = "bestbuy"

    def fetch(
        self,
        client: httpx.Client,
        provider_config: dict[str, Any],
    ) -> tuple[list[RawListing], ProviderRunResult]:
        api_key = os.getenv("BESTBUY_API_KEY", "").strip()
        if not api_key:
            return [], ProviderRunResult(
                provider=self.name,
                status="skipped",
                listing_count=0,
                message="BESTBUY_API_KEY not set (optional)",
            )

        page_size = int(provider_config.get("page_size", 50))
        include_open_box = bool(provider_config.get("include_open_box", True))

        # Gaming laptops category (pcmcat287600050003) with RTX in name/description
        query = "(categoryPath.id=pcmcat287600050003&search=RTX&onlineAvailability=true)"
        url = f"https://api.bestbuy.com/v1/products{query}"
        params = {
            "apiKey": api_key,
            "format": "json",
            "pageSize": page_size,
            "sort": "salePrice.asc",
            "show": (
                "sku,name,salePrice,regularPrice,url,image,condition,"
                "manufacturer,shortDescription,details"
            ),
        }

        try:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            base_listings = parse_bestbuy_products(resp.json())
        except Exception as exc:
            return [], ProviderRunResult(
                provider=self.name,
                status="error",
                listing_count=0,
                message=f"Products API error: {exc}",
            )

        all_listings = list(base_listings)
        open_box_count = 0

        if include_open_box and base_listings:
            base_by_sku = {item.sku: item for item in base_listings if item.sku}
            skus = list(base_by_sku.keys())[:25]
            if skus:
                sku_expr = ",".join(skus)
                ob_url = f"https://api.bestbuy.com/beta/products/openBox(sku in({sku_expr}))"
                try:
                    ob_resp = client.get(ob_url, params={"apiKey": api_key, "format": "json"})
                    if ob_resp.status_code == 200:
                        ob_listings = parse_bestbuy_open_box(ob_resp.json(), base_by_sku)
                        open_box_count = len(ob_listings)
                        all_listings.extend(ob_listings)
                except Exception:
                    # Open-box endpoint is beta; never fail the whole provider over it.
                    pass

        return all_listings, ProviderRunResult(
            provider=self.name,
            status="ok",
            listing_count=len(all_listings),
            message=f"{len(base_listings)} new + {open_box_count} open-box listings",
        )
