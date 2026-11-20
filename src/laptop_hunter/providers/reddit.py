"""Reddit provider for r/LaptopDeals with JSON-first and Atom RSS fallback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import re
from typing import Any
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
import httpx

from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.providers.base import BaseProvider

_URL_RE = re.compile(r"https?://[^\s<>\"'\)\]]+", re.I)
_EXPIRED_FLAIR_RE = re.compile(r"\b(?:expired|out\s+of\s+stock|oos|dead|closed|meta|discussion|request)\b", re.I)
_NON_DEAL_TITLE_RE = re.compile(r"^\s*(?:\[(?:request|discussion|meta|question)\]|weekly\s+request)", re.I)


def _pick_deal_url(post_url: str, selftext: str, permalink: str) -> str:
    """Prefer an external merchant URL over a reddit.com self-post permalink."""
    if post_url and "reddit.com" not in post_url.lower() and "redd.it" not in post_url.lower():
        return post_url
    for match in _URL_RE.findall(selftext or ""):
        lower = match.lower()
        if "reddit.com" not in lower and "redd.it" not in lower and "imgur.com" not in lower:
            return match.rstrip(".,)")
    return permalink or post_url


def _normalize_reddit_post(data: dict[str, Any], subreddit: str) -> RawListing | None:
    """Convert a single Reddit/Arctic-Shift post dict into a RawListing."""
    title = (data.get("title") or "").strip()
    if not title or _NON_DEAL_TITLE_RE.search(title):
        return None

    flair = (data.get("link_flair_text") or "").strip()
    if flair and _EXPIRED_FLAIR_RE.search(flair):
        return None
    if data.get("stickied") or data.get("over_18"):
        return None

    post_id = str(data.get("id") or "")
    raw_permalink = data.get("permalink") or ""
    if raw_permalink.startswith("http"):
        permalink = raw_permalink
    elif raw_permalink:
        permalink = f"https://www.reddit.com{raw_permalink}"
    else:
        permalink = ""

    selftext = (data.get("selftext") or "").strip()
    deal_url = _pick_deal_url(data.get("url") or "", selftext, permalink)

    created_utc = data.get("created_utc")
    posted_at = (
        datetime.fromtimestamp(float(created_utc), tz=timezone.utc).isoformat()
        if created_utc
        else None
    )

    thumbnail = data.get("thumbnail")
    image_url = thumbnail if isinstance(thumbnail, str) and thumbnail.startswith("http") else None

    return RawListing(
        provider="reddit",
        external_id=f"{subreddit}:{post_id}",
        title=title,
        url=deal_url,
        description=selftext[:1200],
        image_url=image_url,
        posted_at=posted_at,
        condition_hint=flair or None,
        upvotes=int(data.get("score")) if data.get("score") is not None else None,
    )


def parse_reddit_json(payload: dict[str, Any], subreddit: str) -> list[RawListing]:
    """Parse Reddit listing JSON into RawListings."""
    listings: list[RawListing] = []
    children = ((payload or {}).get("data") or {}).get("children") or []
    for child in children:
        data = (child or {}).get("data") or {}
        item = _normalize_reddit_post(data, subreddit)
        if item is not None:
            listings.append(item)
    return listings


def parse_arctic_shift_json(payload: dict[str, Any], subreddit: str) -> list[RawListing]:
    """Parse Arctic Shift public Reddit archive API JSON into RawListings."""
    listings: list[RawListing] = []
    for data in (payload or {}).get("data") or []:
        if not isinstance(data, dict):
            continue
        item = _normalize_reddit_post(data, subreddit)
        if item is not None:
            listings.append(item)
    return listings


def parse_reddit_rss(xml_text: str, subreddit: str) -> list[RawListing]:
    """Parse Reddit Atom RSS feed as a fallback when JSON API is rate-limited."""
    listings: list[RawListing] = []
    root = ET.fromstring(xml_text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for entry in root.findall("atom:entry", ns):
        title_el = entry.find("atom:title", ns)
        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title or _NON_DEAL_TITLE_RE.search(title):
            continue

        id_el = entry.find("atom:id", ns)
        entry_id = (id_el.text or title).strip() if id_el is not None else title

        link_el = entry.find("atom:link", ns)
        permalink = link_el.attrib.get("href", "") if link_el is not None else ""

        content_el = entry.find("atom:content", ns)
        content_html = (content_el.text or "") if content_el is not None else ""
        soup = BeautifulSoup(content_html, "html.parser")
        text_body = soup.get_text(" ", strip=True)

        external_url = ""
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            lower = href.lower()
            if href.startswith("http") and "reddit.com" not in lower and "redd.it" not in lower:
                external_url = href
                break

        updated_el = entry.find("atom:updated", ns)
        posted_at = (updated_el.text or "").strip() if updated_el is not None else None

        listings.append(
            RawListing(
                provider="reddit",
                external_id=f"{subreddit}:{entry_id}",
                title=title,
                url=external_url or permalink,
                description=text_body[:1200],
                posted_at=posted_at,
            )
        )
    return listings


class RedditProvider(BaseProvider):
    """Fetch recent laptop deal posts from r/LaptopDeals.

    Automatically uses Reddit OAuth2 (`oauth.reddit.com`) when REDDIT_CLIENT_ID and
    REDDIT_CLIENT_SECRET env vars are set, falling back to public JSON and Atom RSS.
    """

    name = "reddit"

    @staticmethod
    def _get_oauth_token(client: httpx.Client, user_agent: str) -> str | None:
        client_id = os.getenv("REDDIT_CLIENT_ID", "").strip()
        client_secret = os.getenv("REDDIT_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None
        resp = client.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": user_agent},
        )
        resp.raise_for_status()
        return str(resp.json().get("access_token") or "") or None

    def fetch(
        self,
        client: httpx.Client,
        provider_config: dict[str, Any],
    ) -> tuple[list[RawListing], ProviderRunResult]:
        subreddits = provider_config.get("subreddits") or ["LaptopDeals"]
        limit = int(provider_config.get("limit", 60))
        max_age_days = provider_config.get("max_post_age_days", 14)
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=int(max_age_days))
            if max_age_days is not None
            else None
        )
        user_agent = "python:laptop-deal-hunter:v0.1 (GitHub Actions deal monitor)"

        oauth_token: str | None = None
        notes: list[str] = []
        try:
            oauth_token = self._get_oauth_token(client, user_agent)
        except Exception as exc:
            notes.append(f"OAuth failed ({exc}), using public fallback")

        all_listings: list[RawListing] = []

        for sub in subreddits:
            parsed: list[RawListing] = []
            if oauth_token:
                try:
                    resp = client.get(
                        f"https://oauth.reddit.com/r/{sub}/new?limit={limit}&raw_json=1",
                        headers={
                            "User-Agent": user_agent,
                            "Authorization": f"Bearer {oauth_token}",
                        },
                    )
                    resp.raise_for_status()
                    parsed = parse_reddit_json(resp.json(), sub)
                    notes.append(f"r/{sub}: {len(parsed)} via OAuth")
                except Exception as exc:
                    notes.append(f"r/{sub} OAuth error ({exc})")

            if not parsed:
                # Arctic Shift public Reddit mirror works cleanly with zero API key on cloud IPs
                as_url = "https://arctic-shift.photon-reddit.com/api/posts/search"
                try:
                    as_resp = client.get(
                        as_url,
                        params={
                            "subreddit": sub,
                            "limit": min(limit, 100),
                            "sort": "desc",
                        },
                        headers={"User-Agent": user_agent},
                    )
                    if as_resp.status_code == 200:
                        parsed = parse_arctic_shift_json(as_resp.json(), sub)
                        notes.append(f"r/{sub}: {len(parsed)} via Arctic Shift")
                    else:
                        notes.append(f"r/{sub} Arctic Shift HTTP {as_resp.status_code}")
                except Exception as exc:
                    notes.append(f"r/{sub} Arctic Shift error ({exc})")

            if not parsed:
                headers = {"User-Agent": user_agent}
                json_url = f"https://www.reddit.com/r/{sub}/new.json?limit={limit}&raw_json=1"
                rss_url = f"https://www.reddit.com/r/{sub}/new.rss?limit={limit}"
                try:
                    resp = client.get(json_url, headers=headers)
                    if resp.status_code == 200:
                        parsed = parse_reddit_json(resp.json(), sub)
                        notes.append(f"r/{sub}: {len(parsed)} via JSON")
                    else:
                        notes.append(f"r/{sub} JSON HTTP {resp.status_code}, trying RSS")
                except Exception as exc:
                    notes.append(f"r/{sub} JSON error ({exc}), trying RSS")

                if not parsed:
                    try:
                        rss_resp = client.get(rss_url, headers=headers)
                        rss_resp.raise_for_status()
                        parsed = parse_reddit_rss(rss_resp.text, sub)
                        notes.append(f"r/{sub}: {len(parsed)} via RSS")
                    except Exception as exc:
                        notes.append(f"r/{sub} RSS error ({exc})")

            for item in parsed:
                if cutoff and item.posted_at:
                    try:
                        dt = datetime.fromisoformat(item.posted_at.replace("Z", "+00:00"))
                        if dt.tzinfo is None:
                            dt = dt.replace(tzinfo=timezone.utc)
                        if dt < cutoff:
                            continue
                    except ValueError:
                        pass
                all_listings.append(item)

        status = "ok" if all_listings else "error"
        return all_listings, ProviderRunResult(
            provider=self.name,
            status=status,
            listing_count=len(all_listings),
            message="; ".join(notes),
        )
