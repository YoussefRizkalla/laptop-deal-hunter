"""Base provider interface and shared HTTP client utilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import httpx

from laptop_hunter.models import ProviderRunResult, RawListing

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; LaptopDealHunter/0.1; +https://github.com/topics/laptop-deals)"
)


def create_http_client(timeout_seconds: float = 20.0) -> httpx.Client:
    """Create a configured synchronous HTTPX client."""
    return httpx.Client(
        timeout=httpx.Timeout(timeout_seconds),
        follow_redirects=True,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, application/xml, text/xml, text/html;q=0.9, */*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )


class BaseProvider(ABC):
    """Abstract base class for all deal source providers."""

    name: str = "base"

    @abstractmethod
    def fetch(
        self,
        client: httpx.Client,
        provider_config: dict[str, Any],
    ) -> tuple[list[RawListing], ProviderRunResult]:
        """Fetch raw listings from this source."""
