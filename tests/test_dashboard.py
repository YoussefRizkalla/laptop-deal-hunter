"""Tests for static GitHub Pages dashboard generation."""

from datetime import datetime, timezone
import json
from pathlib import Path

from laptop_hunter.config import load_config
from laptop_hunter.dashboard import generate_dashboard
from laptop_hunter.evaluator import evaluate_all
from laptop_hunter.models import ProviderRunResult, RawListing
from laptop_hunter.storage import StateStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_generate_dashboard_writes_html_and_data_json(tmp_path: Path) -> None:
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = StateStore()
    now = datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc)

    listings = [
        RawListing(
            provider="reddit",
            external_id="1",
            title='[Best Buy] ASUS ROG Zephyrus G16 16" OLED RTX 5070 Ti 32GB 2TB SSD - $1,499 (was $2,099)',
            url="https://www.bestbuy.com/site/g16/1",
        ),
        RawListing(
            provider="slickdeals",
            external_id="2",
            title="Lenovo Legion Pro 5 RTX 5070 16GB RAM 1TB SSD - $1,099",
            url="https://slickdeals.net/f/2",
        ),
    ]
    evals = evaluate_all(listings, cfg, store)
    store.record_run(
        evals,
        [ProviderRunResult(provider="reddit", status="ok", listing_count=2)],
        cfg,
        now=now,
    )

    index_path = generate_dashboard(store, cfg, tmp_path / "site", now=now)
    assert index_path.exists()
    html = index_path.read_text(encoding="utf-8")
    assert "Gaming Laptop Deal Hunter" in html
    assert "RTX 5070 Ti" in html

    data_json = json.loads((tmp_path / "site" / "data.json").read_text(encoding="utf-8"))
    assert len(data_json["matches"]) == 1
    assert len(data_json["near_misses"]) == 1
    assert data_json["matches"][0]["current_price_usd"] == 1499.0
