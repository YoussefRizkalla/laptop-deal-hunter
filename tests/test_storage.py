"""Tests for state persistence, price history aggregation, and change detection."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from laptop_hunter.config import load_config
from laptop_hunter.evaluator import evaluate_all
from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.storage import StateStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_state_store_roundtrip_and_change_detection(tmp_path: Path) -> None:
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = StateStore()
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    listing = RawListing(
        provider="reddit",
        external_id="1",
        title="[Best Buy] ASUS ROG Zephyrus G16 RTX 5070 Ti 32GB RAM 2TB SSD - $1,499",
        url="https://www.bestbuy.com/site/g16/111?utm_source=reddit",
    )
    evals = evaluate_all([listing], cfg, store)
    changed_first = store.record_run(
        evals,
        [ProviderRunResult(provider="reddit", status="ok", listing_count=1)],
        cfg,
        now=now,
    )
    assert changed_first is True

    # Running again with identical price should NOT mark meaningful change
    evals_second = evaluate_all([listing], cfg, store)
    changed_second = store.record_run(
        evals_second,
        [ProviderRunResult(provider="reddit", status="ok", listing_count=1)],
        cfg,
        now=now + timedelta(minutes=20),
    )
    assert changed_second is False

    # Saving and reloading preserves history and GPU series
    state_file = tmp_path / "state.json"
    store.save(state_file)
    reloaded = StateStore.load(state_file)
    assert reloaded.data["runs_count"] == 2
    assert "RTX 5070 Ti" in reloaded.data["gpu_history"]
    assert reloaded.data["gpu_history"]["RTX 5070 Ti"][0]["min_price_usd"] == pytest.approx(1499.0)
