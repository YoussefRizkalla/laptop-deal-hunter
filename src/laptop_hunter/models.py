"""Core data models for listings, parsed specs, evaluations, and price history."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class RawListing:
    """Normalized listing emitted by a deal provider before spec parsing."""

    provider: str
    external_id: str
    title: str
    url: str
    price_usd: float | None = None
    msrp_usd: float | None = None
    store: str | None = None
    description: str = ""
    image_url: str | None = None
    posted_at: str | None = None
    condition_hint: str | None = None
    upvotes: int | None = None
    sku: str | None = None
    raw_specs: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedSpecs:
    """Structured laptop specifications extracted from a listing."""

    gpu: str | None = None
    ram_gb: int | None = None
    ssd_gb: int | None = None
    cpu: str | None = None
    brand: str | None = None
    model_name: str | None = None
    screen_inches: float | None = None
    panel_type: str | None = None
    resolution: str | None = None
    refresh_hz: int | None = None
    condition: str = "new"  # new | open_box | refurbished | used
    price_usd: float | None = None
    msrp_usd: float | None = None
    store: str | None = None
    discount_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def summary_parts(self) -> list[str]:
        """Return compact human-readable spec pills."""
        parts: list[str] = []
        if self.gpu:
            parts.append(self.gpu)
        if self.ram_gb:
            parts.append(f"{self.ram_gb}GB RAM")
        if self.ssd_gb:
            if self.ssd_gb >= 1000 and self.ssd_gb % 1000 == 0:
                parts.append(f"{self.ssd_gb // 1000}TB SSD")
            elif self.ssd_gb >= 1024 and self.ssd_gb % 1024 == 0:
                parts.append(f"{self.ssd_gb // 1024}TB SSD")
            else:
                parts.append(f"{self.ssd_gb}GB SSD")
        if self.cpu:
            parts.append(self.cpu)
        display_bits: list[str] = []
        if self.screen_inches:
            inches = f"{self.screen_inches:g}\""
            display_bits.append(inches)
        if self.resolution:
            display_bits.append(self.resolution)
        if self.panel_type:
            display_bits.append(self.panel_type)
        if self.refresh_hz:
            display_bits.append(f"{self.refresh_hz}Hz")
        if display_bits:
            parts.append(" ".join(display_bits))
        return parts


@dataclass
class DealEvaluation:
    """Result of evaluating a parsed listing against user rules and price history."""

    deal_id: str
    model_key: str
    listing: RawListing
    specs: ParsedSpecs
    category: str  # match | near_miss | rejected
    rejection_reason: str | None = None
    near_miss_reasons: list[str] = field(default_factory=list)
    effective_target_usd: float | None = None
    triggers: list[str] = field(default_factory=list)
    should_alert: bool = False
    alert_priority: int = 0
    price_vs_target_usd: float | None = None
    historical_low_usd: float | None = None
    previous_alerted_price_usd: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "deal_id": self.deal_id,
            "model_key": self.model_key,
            "listing": self.listing.to_dict(),
            "specs": self.specs.to_dict(),
            "category": self.category,
            "rejection_reason": self.rejection_reason,
            "near_miss_reasons": list(self.near_miss_reasons),
            "effective_target_usd": self.effective_target_usd,
            "triggers": list(self.triggers),
            "should_alert": self.should_alert,
            "alert_priority": self.alert_priority,
            "price_vs_target_usd": self.price_vs_target_usd,
            "historical_low_usd": self.historical_low_usd,
            "previous_alerted_price_usd": self.previous_alerted_price_usd,
        }


@dataclass
class ProviderRunResult:
    """Execution summary for a single data provider."""

    provider: str
    status: str  # ok | skipped | error
    listing_count: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
