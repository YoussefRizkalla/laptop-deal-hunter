"""Configuration loading and validation from config.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class GpuTarget:
    """Target pricing and tier metadata for a single GPU model."""

    name: str
    tier: int
    target_price_usd: float


@dataclass(frozen=True)
class SpecsConfig:
    min_ram_gb: int = 32
    min_ssd_gb: int = 1000
    max_price_usd: float | None = None
    gpu_targets: dict[str, GpuTarget] = field(default_factory=dict)
    exclude_brands: tuple[str, ...] = ()
    exclude_keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConditionsConfig:
    allowed: tuple[str, ...] = ("new", "open_box", "refurbished")
    non_new_price_multiplier: float = 0.90


@dataclass(frozen=True)
class AlertsConfig:
    min_steep_discount_pct: float = 25.0
    steep_discount_max_target_ratio: float = 1.15
    alert_on_historical_low: bool = True
    historical_low_min_samples: int = 3
    alert_unconfirmed_specs_if_extreme: bool = True
    unconfirmed_extreme_price_ratio: float = 0.85
    min_redrop_usd: float = 25.0
    min_redrop_pct: float = 3.0
    max_alerts_per_run: int = 10


@dataclass(frozen=True)
class StorageConfig:
    history_retention_days: int = 180
    stale_deal_days: int = 7


@dataclass(frozen=True)
class DashboardConfig:
    title: str = "Gaming Laptop Deal Hunter"
    subtitle: str = "Tracking RTX 5070+ • 32GB+ RAM • 1TB+ SSD deals across the web"


@dataclass(frozen=True)
class AppConfig:
    specs: SpecsConfig
    conditions: ConditionsConfig
    alerts: AlertsConfig
    providers: dict[str, dict[str, Any]]
    storage: StorageConfig
    dashboard: DashboardConfig

    def get_gpu_target(self, gpu_name: str | None) -> GpuTarget | None:
        if not gpu_name:
            return None
        return self.specs.gpu_targets.get(gpu_name)


def _load_gpu_targets(raw: dict[str, Any]) -> dict[str, GpuTarget]:
    targets: dict[str, GpuTarget] = {}
    for gpu_name, entry in (raw or {}).items():
        if isinstance(entry, (int, float)):
            targets[str(gpu_name)] = GpuTarget(
                name=str(gpu_name),
                tier=1,
                target_price_usd=float(entry),
            )
        elif isinstance(entry, dict):
            targets[str(gpu_name)] = GpuTarget(
                name=str(gpu_name),
                tier=int(entry.get("tier", 1)),
                target_price_usd=float(entry["target_price_usd"]),
            )
        else:
            raise ValueError(f"Invalid gpu_targets entry for {gpu_name!r}: {entry!r}")
    return targets


def load_config(path: str | Path) -> AppConfig:
    """Load and validate an AppConfig from a YAML file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    if not isinstance(raw, dict):
        raise ValueError("Top-level config.yaml content must be a YAML mapping")

    specs_raw = raw.get("specs") or {}
    max_price = specs_raw.get("max_price_usd")
    specs = SpecsConfig(
        min_ram_gb=int(specs_raw.get("min_ram_gb", 32)),
        min_ssd_gb=int(specs_raw.get("min_ssd_gb", 1000)),
        max_price_usd=float(max_price) if max_price is not None else None,
        gpu_targets=_load_gpu_targets(specs_raw.get("gpu_targets") or {}),
        exclude_brands=tuple(str(b).strip().lower() for b in (specs_raw.get("exclude_brands") or [])),
        exclude_keywords=tuple(str(k).strip().lower() for k in (specs_raw.get("exclude_keywords") or [])),
    )

    if not specs.gpu_targets:
        raise ValueError("config.yaml must define at least one entry in specs.gpu_targets")

    cond_raw = raw.get("conditions") or {}
    conditions = ConditionsConfig(
        allowed=tuple(str(c).strip().lower() for c in (cond_raw.get("allowed") or ("new", "open_box", "refurbished"))),
        non_new_price_multiplier=float(cond_raw.get("non_new_price_multiplier", 0.90)),
    )

    alerts_raw = raw.get("alerts") or {}
    alerts = AlertsConfig(
        min_steep_discount_pct=float(alerts_raw.get("min_steep_discount_pct", 25.0)),
        steep_discount_max_target_ratio=float(alerts_raw.get("steep_discount_max_target_ratio", 1.15)),
        alert_on_historical_low=bool(alerts_raw.get("alert_on_historical_low", True)),
        historical_low_min_samples=int(alerts_raw.get("historical_low_min_samples", 3)),
        alert_unconfirmed_specs_if_extreme=bool(alerts_raw.get("alert_unconfirmed_specs_if_extreme", True)),
        unconfirmed_extreme_price_ratio=float(alerts_raw.get("unconfirmed_extreme_price_ratio", 0.85)),
        min_redrop_usd=float(alerts_raw.get("min_redrop_usd", 25.0)),
        min_redrop_pct=float(alerts_raw.get("min_redrop_pct", 3.0)),
        max_alerts_per_run=int(alerts_raw.get("max_alerts_per_run", 10)),
    )

    storage_raw = raw.get("storage") or {}
    storage = StorageConfig(
        history_retention_days=int(storage_raw.get("history_retention_days", 180)),
        stale_deal_days=int(storage_raw.get("stale_deal_days", 7)),
    )

    dash_raw = raw.get("dashboard") or {}
    dashboard = DashboardConfig(
        title=str(dash_raw.get("title", "Gaming Laptop Deal Hunter")),
        subtitle=str(dash_raw.get("subtitle", "Tracking RTX 5070+ • 32GB+ RAM • 1TB+ SSD deals across the web")),
    )

    providers = raw.get("providers") or {}
    if not isinstance(providers, dict):
        raise ValueError("providers section must be a mapping")

    return AppConfig(
        specs=specs,
        conditions=conditions,
        alerts=alerts,
        providers=providers,
        storage=storage,
        dashboard=dashboard,
    )
