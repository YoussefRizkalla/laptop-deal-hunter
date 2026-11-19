"""Provider registry and resilient fan-out runner."""

from __future__ import annotations

from laptop_hunter.config import AppConfig
from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.providers.base import BaseProvider, create_http_client
from laptop_hunter.providers.bestbuy import BestBuyProvider
from laptop_hunter.providers.dealnews import DealNewsProvider
from laptop_hunter.providers.gaminglaptop import GamingLaptopDealsProvider
from laptop_hunter.providers.reddit import RedditProvider
from laptop_hunter.providers.slickdeals import SlickdealsProvider

PROVIDER_REGISTRY: dict[str, BaseProvider] = {
    "slickdeals": SlickdealsProvider(),
    "dealnews": DealNewsProvider(),
    "reddit": RedditProvider(),
    "bestbuy": BestBuyProvider(),
    "gaminglaptop": GamingLaptopDealsProvider(),
}


def fetch_all_providers(
    config: AppConfig,
) -> tuple[list[RawListing], list[ProviderRunResult]]:
    """Fetch listings from all enabled providers, isolating individual provider failures."""
    all_listings: list[RawListing] = []
    results: list[ProviderRunResult] = []

    with create_http_client() as client:
        for name, provider in PROVIDER_REGISTRY.items():
            prov_cfg = config.providers.get(name) or {}
            if not prov_cfg.get("enabled", False):
                results.append(
                    ProviderRunResult(
                        provider=name,
                        status="skipped",
                        listing_count=0,
                        message="Disabled in config.yaml",
                    )
                )
                continue

            try:
                listings, result = provider.fetch(client, prov_cfg)
                all_listings.extend(listings)
                results.append(result)
            except Exception as exc:
                results.append(
                    ProviderRunResult(
                        provider=name,
                        status="error",
                        listing_count=0,
                        message=f"Unexpected provider failure: {exc}",
                    )
                )

    return all_listings, results
