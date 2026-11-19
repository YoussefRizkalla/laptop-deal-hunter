"""Slickdeals RSS search provider."""

from __future__ import annotations

from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import httpx

from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.providers.base import BaseProvider


def _parse_pubdate(raw_date: str | None) -> str | None:
    if not raw_date:
        return None
    try:
        dt = parsedate_to_datetime(raw_date)
        return dt.isoformat()
    except Exception:
        return raw_date.strip()


def parse_slickdeals_rss(xml_text: str) -> list[RawListing]:
    """Parse Slickdeals RSS 2.0 XML into RawListings."""
    listings: list[RawListing] = []
    root = ET.fromstring(xml_text)

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue

        guid = (item.findtext("guid") or link).strip()
        desc_html = item.findtext("description") or ""
        soup = BeautifulSoup(desc_html, "html.parser")
        desc_text = soup.get_text(" ", strip=True)

        img = soup.find("img")
        image_url = str(img["src"]) if img and img.get("src", "").startswith("http") else None

        listings.append(
            RawListing(
                provider="slickdeals",
                external_id=guid,
                title=title,
                url=link,
                description=desc_text[:1200],
                image_url=image_url,
                posted_at=_parse_pubdate(item.findtext("pubDate")),
            )
        )

    return listings


class SlickdealsProvider(BaseProvider):
    """Fetch gaming laptop deals from Slickdeals RSS search feeds."""

    name = "slickdeals"

    def fetch(
        self,
        client: httpx.Client,
        provider_config: dict[str, Any],
    ) -> tuple[list[RawListing], ProviderRunResult]:
        queries = provider_config.get("queries") or [
            "gaming laptop rtx 5070",
            "gaming laptop rtx 5080",
            "gaming laptop rtx 4080",
        ]

        seen_ids: set[str] = set()
        listings: list[RawListing] = []
        errors: list[str] = []

        for query in queries:
            encoded = quote_plus(str(query))
            url = (
                "https://slickdeals.net/newsearch.php"
                f"?mode=frontpage&searcharea=deals&searchin=first&rss=1&q={encoded}"
            )
            try:
                resp = client.get(url)
                resp.raise_for_status()
                for item in parse_slickdeals_rss(resp.text):
                    if item.external_id not in seen_ids:
                        seen_ids.add(item.external_id)
                        listings.append(item)
            except Exception as exc:
                errors.append(f"{query!r}: {exc}")

        if listings:
            msg = f"{len(listings)} unique listings across {len(queries)} queries"
            if errors:
                msg += f" ({len(errors)} query errors)"
            return listings, ProviderRunResult(
                provider=self.name,
                status="ok",
                listing_count=len(listings),
                message=msg,
            )

        status = "error" if errors else "ok"
        return [], ProviderRunResult(
            provider=self.name,
            status=status,
            listing_count=0,
            message="; ".join(errors) if errors else "0 listings matched RSS queries",
        )
