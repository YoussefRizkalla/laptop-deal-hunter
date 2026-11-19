"""Diff-friendly JSON persistence for deals, alert state, and price history."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from statistics import median
from typing import Any

from laptop_hunter.config import AppConfig
from laptop_hunter.models import DealEvaluation, ProviderRunResult

STATE_SCHEMA_VERSION = 1


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


class StateStore:
    """Manages tracked deals, historical lows, and daily GPU price series."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data: dict[str, Any] = data or {
            "version": STATE_SCHEMA_VERSION,
            "last_run_at": None,
            "runs_count": 0,
            "last_provider_results": [],
            "deals": {},
            "gpu_history": {},
            "model_lows": {},
        }
        self.data.setdefault("version", STATE_SCHEMA_VERSION)
        self.data.setdefault("deals", {})
        self.data.setdefault("gpu_history", {})
        self.data.setdefault("model_lows", {})
        self.data.setdefault("last_provider_results", [])
        self.data.setdefault("runs_count", 0)

    @classmethod
    def load(cls, path: str | Path) -> StateStore:
        file_path = Path(path)
        if not file_path.exists():
            return cls()
        with file_path.open("r", encoding="utf-8") as handle:
            raw = json.load(handle)
        return cls(raw)

    def save(self, path: str | Path) -> None:
        file_path = Path(path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with file_path.open("w", encoding="utf-8") as handle:
            json.dump(self.data, handle, indent=2, sort_keys=True)
            handle.write("\n")

    def get_previous_alerted_price(self, deal_id: str) -> float | None:
        deal = self.data["deals"].get(deal_id)
        if not deal:
            return None
        val = deal.get("last_alerted_price_usd")
        return float(val) if val is not None else None

    def get_gpu_tier_low(self, gpu: str, condition: str = "new") -> tuple[float | None, int]:
        """Return (lowest_seen_price_usd, observation_count) for a GPU tier."""
        # Prefer historical lows computed across tracked match deals of matching condition
        prices: list[float] = []
        samples = 0
        for deal in self.data["deals"].values():
            specs = deal.get("specs") or {}
            if deal.get("category") != "match":
                continue
            if specs.get("gpu") != gpu:
                continue
            if condition == "new" and specs.get("condition", "new") != "new":
                continue
            low = deal.get("lowest_price_usd")
            if low is not None:
                prices.append(float(low))
                samples += max(1, len(deal.get("price_history") or []))

        # Also incorporate daily series points for longer-horizon history
        for point in self.data["gpu_history"].get(gpu) or []:
            if point.get("min_price_usd") is not None:
                prices.append(float(point["min_price_usd"]))
                samples = max(samples, int(point.get("sample_count", 1)))

        if not prices:
            return None, 0
        return min(prices), samples

    def get_model_low(self, model_key: str) -> tuple[float | None, int]:
        entry = self.data["model_lows"].get(model_key)
        if not entry:
            return None, 0
        low = entry.get("lowest_price_usd")
        return (float(low) if low is not None else None), int(entry.get("samples", 0))

    def record_run(
        self,
        evaluations: list[DealEvaluation],
        provider_results: list[ProviderRunResult],
        config: AppConfig,
        now: datetime | None = None,
    ) -> bool:
        """Merge current run evaluations into state. Returns True if meaningful data changed."""
        now_dt = now or utc_now()
        now_iso = now_dt.isoformat()
        today_str = now_dt.strftime("%Y-%m-%d")

        before_snapshot = self._meaningful_fingerprint()

        deals_map: dict[str, dict[str, Any]] = self.data["deals"]
        model_lows: dict[str, dict[str, Any]] = self.data["model_lows"]

        active_evals = [e for e in evaluations if e.category in ("match", "near_miss")]

        # Track per-GPU prices seen in this run (strict matches only for clean GPU chart baselines)
        gpu_prices_today: dict[str, list[float]] = {}

        for ev in active_evals:
            price = ev.specs.price_usd
            if price is None:
                continue

            existing = deals_map.get(ev.deal_id)
            if existing is None:
                existing = {
                    "deal_id": ev.deal_id,
                    "model_key": ev.model_key,
                    "category": ev.category,
                    "title": ev.listing.title,
                    "url": ev.listing.url,
                    "provider": ev.listing.provider,
                    "store": ev.specs.store or ev.listing.store or ev.listing.provider,
                    "image_url": ev.listing.image_url,
                    "upvotes": ev.listing.upvotes,
                    "specs": ev.specs.to_dict(),
                    "effective_target_usd": ev.effective_target_usd,
                    "triggers": list(ev.triggers),
                    "near_miss_reasons": list(ev.near_miss_reasons),
                    "alert_priority": ev.alert_priority,
                    "first_seen_at": now_iso,
                    "last_seen_at": now_iso,
                    "current_price_usd": price,
                    "lowest_price_usd": price,
                    "last_alerted_at": None,
                    "last_alerted_price_usd": None,
                    "price_history": [{"ts": now_iso, "price_usd": price}],
                }
                deals_map[ev.deal_id] = existing
            else:
                existing["model_key"] = ev.model_key
                existing["category"] = ev.category
                existing["title"] = ev.listing.title
                existing["url"] = ev.listing.url
                existing["store"] = ev.specs.store or ev.listing.store or existing.get("store")
                if ev.listing.image_url:
                    existing["image_url"] = ev.listing.image_url
                if ev.listing.upvotes is not None:
                    existing["upvotes"] = ev.listing.upvotes
                existing["specs"] = ev.specs.to_dict()
                existing["effective_target_usd"] = ev.effective_target_usd
                existing["triggers"] = list(ev.triggers)
                existing["near_miss_reasons"] = list(ev.near_miss_reasons)
                existing["alert_priority"] = ev.alert_priority
                existing["last_seen_at"] = now_iso
                existing["current_price_usd"] = price
                prev_low = existing.get("lowest_price_usd")
                existing["lowest_price_usd"] = min(float(prev_low), price) if prev_low is not None else price

                history = existing.setdefault("price_history", [])
                if not history or float(history[-1]["price_usd"]) != price:
                    history.append({"ts": now_iso, "price_usd": price})
                # Keep per-deal history compact
                if len(history) > 60:
                    existing["price_history"] = history[-60:]

            # Update per-model historical low
            if ev.category == "match":
                m_entry = model_lows.get(ev.model_key)
                if m_entry is None:
                    model_lows[ev.model_key] = {
                        "lowest_price_usd": price,
                        "samples": 1,
                        "last_seen_at": now_iso,
                    }
                else:
                    m_entry["lowest_price_usd"] = min(float(m_entry["lowest_price_usd"]), price)
                    m_entry["samples"] = int(m_entry.get("samples", 0)) + 1
                    m_entry["last_seen_at"] = now_iso

                if ev.specs.gpu and ev.specs.condition == "new":
                    gpu_prices_today.setdefault(ev.specs.gpu, []).append(price)

        # Update daily GPU price history series
        gpu_history: dict[str, list[dict[str, Any]]] = self.data["gpu_history"]
        retention_cutoff = (now_dt - timedelta(days=config.storage.history_retention_days)).strftime("%Y-%m-%d")

        for gpu, prices in gpu_prices_today.items():
            series = gpu_history.setdefault(gpu, [])
            day_min = round(min(prices), 2)
            day_med = round(float(median(prices)), 2)

            if series and series[-1].get("date") == today_str:
                prev = series[-1]
                prev["min_price_usd"] = min(float(prev["min_price_usd"]), day_min)
                prev["median_price_usd"] = day_med
                prev["sample_count"] = max(int(prev.get("sample_count", 0)), len(prices))
            else:
                series.append(
                    {
                        "date": today_str,
                        "min_price_usd": day_min,
                        "median_price_usd": day_med,
                        "sample_count": len(prices),
                    }
                )

            gpu_history[gpu] = [pt for pt in series if str(pt.get("date", "")) >= retention_cutoff]

        # Prune ancient deals well past retention window (keep active + recent deals)
        deal_prune_cutoff = now_dt - timedelta(days=config.storage.history_retention_days)
        for deal_id in list(deals_map.keys()):
            last_seen = _parse_iso(deals_map[deal_id].get("last_seen_at"))
            if last_seen and last_seen < deal_prune_cutoff:
                del deals_map[deal_id]

        self.data["last_run_at"] = now_iso
        self.data["runs_count"] = int(self.data.get("runs_count", 0)) + 1
        self.data["last_provider_results"] = [r.to_dict() for r in provider_results]

        after_snapshot = self._meaningful_fingerprint()
        return before_snapshot != after_snapshot

    def mark_alerted(self, evaluations: list[DealEvaluation], now: datetime | None = None) -> None:
        now_iso = (now or utc_now()).isoformat()
        deals_map = self.data["deals"]
        for ev in evaluations:
            deal = deals_map.get(ev.deal_id)
            if deal and ev.specs.price_usd is not None:
                deal["last_alerted_at"] = now_iso
                deal["last_alerted_price_usd"] = ev.specs.price_usd

    def active_deals(self, stale_days: int = 7, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return deals seen within `stale_days`, sorted by priority then price."""
        cutoff = (now or utc_now()) - timedelta(days=stale_days)
        items: list[dict[str, Any]] = []
        for deal in self.data["deals"].values():
            last_seen = _parse_iso(deal.get("last_seen_at"))
            if last_seen is None or last_seen >= cutoff:
                items.append(deal)
        items.sort(
            key=lambda d: (
                0 if d.get("category") == "match" else 1,
                -int(d.get("alert_priority", 0)),
                float(d.get("current_price_usd", 999999)),
            )
        )
        return items

    def _meaningful_fingerprint(self) -> str:
        """Fingerprint ignoring timestamps-only churn so unchanged runs skip empty commits."""
        deals_summary = {
            did: {
                "cat": d.get("category"),
                "price": d.get("current_price_usd"),
                "low": d.get("lowest_price_usd"),
                "alerted": d.get("last_alerted_price_usd"),
                "triggers": d.get("triggers"),
            }
            for did, d in sorted(self.data.get("deals", {}).items())
        }
        return json.dumps(
            {
                "deals": deals_summary,
                "gpu_history": self.data.get("gpu_history", {}),
            },
            sort_keys=True,
        )
