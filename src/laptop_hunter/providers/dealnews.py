"""DealNews official RSS provider for curated US laptop deals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any
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


def parse_dealnews_rss(
    xml_text: str,
    max_age_days: int | None = 14,
    now: datetime | None = None,
) -> list[RawListing]:
    """Parse DealNews RSS 2.0 XML into RawListings."""
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
                provider="dealnews",
                external_id=f"dn:{guid}",
                title=title,
                url=link,
                description=desc_text[:1200],
                image_url=image_url,
                posted_at=pub_dt.isoformat() if pub_dt else None,
            )
        )

    return listings


class DealNewsProvider(BaseProvider):
    """Fetch curated laptop deals from DealNews official RSS feeds."""

    name = "dealnews"

    def fetch(
        self,
        client: httpx.Client,
        provider_config: dict[str, Any],
    ) -> tuple[list[RawListing], ProviderRunResult]:
        feeds = provider_config.get("feeds") or [
            "https://www.dealnews.com/c49/Computers/Laptops/?rss=1",
        ]
        max_age_days = provider_config.get("max_post_age_days", 14)

        seen: set[str] = set()
        listings: list[RawListing] = []
        errors: list[str] = []

        for feed_url in feeds:
            try:
                resp = client.get(str(feed_url))
                resp.raise_for_status()
                for item in parse_dealnews_rss(resp.text, max_age_days=max_age_days):
                    if item.external_id not in seen:
                        seen.add(item.external_id)
                        listings.append(item)
            except Exception as exc:
                errors.append(f"{feed_url}: {exc}")

        if listings:
            msg = f"{len(listings)} listings from {len(feeds)} feed(s)"
            if errors:
                msg += f" ({len(errors)} error(s))"
            return listings, ProviderRunResult(
                provider=self.name,
                status="ok",
                listing_count=len(listings),
                message=msg,
            )

        return [], ProviderRunResult(
            provider=self.name,
            status="error" if errors else "ok",
            listing_count=0,
            message="; ".join(errors) if errors else "0 recent laptop listings",
        )
