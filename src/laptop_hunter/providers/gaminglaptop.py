"""GamingLaptop.deals HTML scraper provider."""

from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import httpx

from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.parser import extract_gpu, extract_prices
from laptop_hunter.providers.base import BaseProvider

_WHITESPACE_RE = re.compile(r"\s+")


def _clean_text(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", value or "").strip()


def parse_gaminglaptop_html(html: str, base_url: str = "https://gaminglaptop.deals/") -> list[RawListing]:
    """Extract gaming laptop deals from GamingLaptop.deals HTML.

    Supports both card-based layouts (<article>, .deal, .laptop) and table rows (<tr>)
    so minor site redesigns do not break scraping.
    """
    soup = BeautifulSoup(html, "html.parser")
    listings: list[RawListing] = []
    seen_keys: set[str] = set()

    # Prefer structured cards or table rows; fall back to anchor-bearing blocks containing a GPU & $.
    containers = soup.select("article, tr, .deal, .deal-card, .laptop-card, [data-gpu], li.product")
    if not containers:
        containers = soup.find_all(["div", "section"])

    for node in containers:
        text = _clean_text(node.get_text(" ", strip=True))
        if len(text) < 20 or len(text) > 900 or "$" not in text:
            continue
        if not extract_gpu(text):
            continue

        sale_price, msrp = extract_prices(text)
        if sale_price is None:
            continue

        # Pick best outbound deal link inside the container
        link_el = None
        for anchor in node.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.startswith("#") or href.startswith("javascript:"):
                continue
            link_el = anchor
            if "gaminglaptop.deals" not in href.lower():
                break

        if link_el is None:
            continue

        deal_url = urljoin(base_url, str(link_el["href"]).strip())

        heading = node.find(["h1", "h2", "h3", "h4"])
        title = _clean_text(heading.get_text(" ", strip=True)) if heading else ""
        if not title or len(title) < 12:
            title = text[:220]

        # Ensure specs from card body are available in description
        description = text if title != text else ""

        img = node.find("img")
        image_url = None
        if img:
            src = img.get("src") or img.get("data-src")
            if isinstance(src, str) and src.strip():
                image_url = urljoin(base_url, src.strip())

        dedup_key = hashlib.sha1(f"{deal_url}|{title}|{sale_price}".encode("utf-8")).hexdigest()[:16]
        if dedup_key in seen_keys:
            continue
        seen_keys.add(dedup_key)

        listings.append(
            RawListing(
                provider="gaminglaptop",
                external_id=dedup_key,
                title=title,
                url=deal_url,
                price_usd=sale_price,
                msrp_usd=msrp,
                description=description,
                image_url=image_url,
            )
        )

    return listings


class GamingLaptopDealsProvider(BaseProvider):
    """Scrape curated deals from GamingLaptop.deals."""

    name = "gaminglaptop"

    def fetch(
        self,
        client: httpx.Client,
        provider_config: dict[str, Any],
    ) -> tuple[list[RawListing], ProviderRunResult]:
        url = str(provider_config.get("url") or "https://gaminglaptop.deals/")
        try:
            resp = client.get(url)
            resp.raise_for_status()
            listings = parse_gaminglaptop_html(resp.text, base_url=url)
            return listings, ProviderRunResult(
                provider=self.name,
                status="ok",
                listing_count=len(listings),
                message=f"Parsed {len(listings)} laptop deals from {url}",
            )
        except Exception as exc:
            return [], ProviderRunResult(
                provider=self.name,
                status="error",
                listing_count=0,
                message=str(exc),
            )
