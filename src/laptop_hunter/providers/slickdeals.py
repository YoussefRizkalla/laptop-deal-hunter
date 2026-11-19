"""Slickdeals RSS search provider (frontpage, popular, and live forum deals)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import httpx

from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.providers.base import BaseProvider


def _parse_pubdate(raw_date: str | None) -> datetime | None:
    if not raw_date:
        return None
    try:
        dt = parsedate_to_datetime(raw_date)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_slickdeals_rss(
    xml_text: str,
    max_age_days: int | None = 14,
    now: datetime | None = None,
) -> list[RawListing]:
    """Parse Slickdeals RSS 2.0 XML into RawListings, filtering out stale archive deals."""
    listings: list[RawListing] = []
    root = ET.fromstring(xml_text)
    cutoff = (
        (now or datetime.now(timezone.utc)) - timedelta(days=max_age_days)
        if max_age_days is not None
        else None
    )

    for item in root.findall(".//item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        if not title or not link:
            continue

        pub_dt = _parse_pubdate(item.findtext("pubDate"))
        if cutoff and pub_dt and pub_dt < cutoff:
            continue

        guid = (item.findtext("guid") or link).strip()
        desc_raw = item.findtext("description") or ""
        if "<" in desc_raw:
            soup = BeautifulSoup(desc_raw, "html.parser")
            desc_text = soup.get_text(" ", strip=True)
            img = soup.find("img")
            image_url = str(img["src"]) if img and str(img.get("src", "")).startswith("http") else None
        else:
            desc_text = desc_raw.strip()
            image_url = None

        listings.append(
            RawListing(
                provider="slickdeals",
                external_id=guid,
                title=title,
                url=link,
                description=desc_text[:1200],
                image_url=image_url,
                posted_at=pub_dt.isoformat() if pub_dt else None,
            )
        )

    return listings


class SlickdealsProvider(BaseProvider):
    """Fetch recent gaming laptop deals from Slickdeals RSS search feeds."""

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
        modes = provider_config.get("modes") or ["popdeals", "forum"]
        max_age_days = provider_config.get("max_post_age_days", 14)

        seen_ids: set[str] = set()
        listings: list[RawListing] = []
        errors: list[str] = []

        for mode in modes:
            for query in queries:
                encoded = quote_plus(str(query))
                url = (
                    "https://slickdeals.net/newsearch.php"
                    f"?mode={mode}&searcharea=deals&searchin=first&rss=1&q={encoded}"
                )
                try:
                    resp = client.get(url)
                    resp.raise_for_status()
                    for item in parse_slickdeals_rss(resp.text, max_age_days=max_age_days):
                        if item.external_id not in seen_ids:
                            seen_ids.add(item.external_id)
                            listings.append(item)
                except Exception as exc:
                    errors.append(f"{mode}/{query!r}: {exc}")

        if listings:
            msg = f"{len(listings)} recent unique listings across {len(modes)} mode(s) x {len(queries)} queries"
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
            message="; ".join(errors) if errors else "0 recent listings matched RSS queries",
        )
