"""Tests for the deal evaluator: strict alerts, near misses, open-box discount, and anti-spam."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from laptop_hunter.config import load_config
from laptop_hunter.evaluator import evaluate_all, evaluate_listing
from laptop_hunter.models import RawListing
from laptop_hunter.storage import StateStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def _cfg():
    return load_config(REPO_ROOT / "config.yaml")


def test_matching_killer_deal_triggers_alert() -> None:
    cfg = _cfg()
    store = StateStore()
    listing = RawListing(
        provider="reddit",
        external_id="r1",
        title="[Best Buy] Lenovo Legion Pro 7i RTX 5070 Ti 32GB DDR5 2TB SSD - $1,499 (was $2,099)",
        url="https://www.bestbuy.com/site/legion/123",
    )
    ev = evaluate_listing(listing, cfg, store)
    assert ev.category == "match"
    assert "BEATS_TARGET" in ev.triggers
    assert "STEEP_DISCOUNT" in ev.triggers
    assert ev.should_alert is True


def test_lower_gpu_and_desktops_are_rejected() -> None:
    cfg = _cfg()
    store = StateStore()
    rtx4070 = evaluate_listing(
        RawListing(
            provider="reddit",
            external_id="r2",
            title="[Best Buy] ASUS TUF RTX 4070 32GB RAM 1TB SSD - $899",
            url="https://www.bestbuy.com/site/tuf/1",
        ),
        cfg,
        store,
    )
    assert rtx4070.category == "rejected"

    desktop = evaluate_listing(
        RawListing(
            provider="slickdeals",
            external_id="s1",
            title="CyberPowerPC Gaming Desktop RTX 5080 32GB 2TB SSD - $1,699",
            url="https://slickdeals.net/f/999",
        ),
        cfg,
        store,
    )
    assert desktop.category == "rejected"
    assert "desktop" in (desktop.rejection_reason or "").lower()


def test_16gb_deal_goes_to_near_miss_never_alerts_discord() -> None:
    cfg = _cfg()
    store = StateStore()
    listing = RawListing(
        provider="reddit",
        external_id="r3",
        title="[Best Buy] ASUS ROG Strix G16 RTX 5070 Ti 16GB RAM 1TB SSD - $1,199",
        url="https://www.bestbuy.com/site/strix/2",
    )
    ev = evaluate_listing(listing, cfg, store)
    assert ev.category == "near_miss"
    assert any("16GB RAM" in reason for reason in ev.near_miss_reasons)
    assert ev.should_alert is False


def test_unconfirmed_specs_alerts_only_when_extreme_outlier() -> None:
    cfg = _cfg()
    store = StateStore()
    # RTX 5070 Ti target is $1,550; 85% extreme threshold is $1,317.50
    moderate = evaluate_listing(
        RawListing(
            provider="slickdeals",
            external_id="s2",
            title="MSI Vector 16 RTX 5070 Ti Gaming Laptop - $1,450",
            url="https://slickdeals.net/f/100",
        ),
        cfg,
        store,
    )
    assert moderate.category == "near_miss"
    assert moderate.should_alert is False

    extreme = evaluate_listing(
        RawListing(
            provider="slickdeals",
            external_id="s3",
            title="MSI Vector 16 RTX 5070 Ti Gaming Laptop - $1,249",
            url="https://slickdeals.net/f/101",
        ),
        cfg,
        store,
    )
    assert extreme.category == "near_miss"
    assert "EXTREME_UNCONFIRMED" in extreme.triggers
    assert extreme.should_alert is True


def test_open_box_uses_stricter_target_price() -> None:
    cfg = _cfg()
    store = StateStore()
    # RTX 5070 target is $1,250; open_box effective target is $1,125 (0.90x)
    above_ob = evaluate_listing(
        RawListing(
            provider="bestbuy",
            external_id="b1",
            title="[Open-Box Excellent] Acer Predator Helios 16 RTX 5070 32GB RAM 1TB SSD - $1,199",
            url="https://www.bestbuy.com/site/helios/1",
        ),
        cfg,
        store,
    )
    assert above_ob.category == "match"
    assert above_ob.effective_target_usd == pytest.approx(1125.0)
    assert above_ob.should_alert is False

    below_ob = evaluate_listing(
        RawListing(
            provider="bestbuy",
            external_id="b2",
            title="[Open-Box Excellent] Acer Predator Helios 16 RTX 5070 32GB RAM 1TB SSD - $1,099",
            url="https://www.bestbuy.com/site/helios/2",
        ),
        cfg,
        store,
    )
    assert below_ob.category == "match"
    assert "BEATS_TARGET" in below_ob.triggers
    assert below_ob.should_alert is True


def test_anti_spam_blocks_duplicate_alert_until_meaningful_drop() -> None:
    cfg = _cfg()
    store = StateStore()
    now = datetime(2026, 11, 18, 12, 0, tzinfo=timezone.utc)

    listing_1500 = RawListing(
        provider="reddit",
        external_id="r1",
        title="[Best Buy] Legion Pro 7i RTX 5070 Ti 32GB 2TB SSD - $1,500",
        url="https://www.bestbuy.com/site/legion/999",
    )
    ev1 = evaluate_listing(listing_1500, cfg, store)
    assert ev1.should_alert is True
    store.record_run([ev1], [], cfg, now=now)
    store.mark_alerted([ev1], now=now)

    # Small $10 drop should NOT re-alert (min_redrop_usd = $25)
    listing_1490 = RawListing(
        provider="reddit",
        external_id="r1",
        title="[Best Buy] Legion Pro 7i RTX 5070 Ti 32GB 2TB SSD - $1,490",
        url="https://www.bestbuy.com/site/legion/999",
    )
    ev2 = evaluate_listing(listing_1490, cfg, store)
    assert ev2.should_alert is False

    # $50 drop SHOULD re-alert
    listing_1450 = RawListing(
        provider="reddit",
        external_id="r1",
        title="[Best Buy] Legion Pro 7i RTX 5070 Ti 32GB 2TB SSD - $1,450",
        url="https://www.bestbuy.com/site/legion/999",
    )
    ev3 = evaluate_listing(listing_1450, cfg, store)
    assert ev3.should_alert is True
    assert ev3.previous_alerted_price_usd == pytest.approx(1500.0)


def test_cross_provider_url_deduplication_prefers_richer_listing() -> None:
    cfg = _cfg()
    store = StateStore()
    terse = RawListing(
        provider="slickdeals",
        external_id="sd1",
        title="ASUS ROG Zephyrus G16 RTX 5080 - $1,899",
        url="https://www.bestbuy.com/site/g16/555?utm_source=slickdeals&ref=123",
    )
    rich = RawListing(
        provider="reddit",
        external_id="rd1",
        title="[Best Buy] ASUS ROG Zephyrus G16 16\" OLED 240Hz RTX 5080 32GB RAM 2TB SSD - $1,899",
        url="https://www.bestbuy.com/site/g16/555",
    )
    evals = evaluate_all([terse, rich], cfg, store)
    active = [e for e in evals if e.category != "rejected"]
    assert len(active) == 1
    assert active[0].category == "match"
    assert active[0].specs.ram_gb == 32
    assert active[0].specs.ssd_gb == 2000


def test_historical_low_trigger_fires_after_min_samples() -> None:
    cfg = _cfg()
    store = StateStore()
    base_time = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)

    # Seed 3 prior observations of RTX 5080 at $2,150+ (above $2,000 target)
    for idx, price in enumerate((2250, 2200, 2150)):
        listing = RawListing(
            provider="reddit",
            external_id=f"seed{idx}",
            title=f"[Best Buy] Razer Blade 16 RTX 5080 32GB RAM 2TB SSD - ${price}",
            url=f"https://www.bestbuy.com/site/blade/{idx}",
        )
        ev = evaluate_listing(listing, cfg, store)
        store.record_run([ev], [], cfg, now=base_time + timedelta(days=idx))

    # Now an RTX 5080 drops to $2,099 — still above $2,000 target, but a new tracked historical low!
    new_low = evaluate_listing(
        RawListing(
            provider="reddit",
            external_id="low1",
            title="[Best Buy] Razer Blade 16 RTX 5080 32GB RAM 2TB SSD - $2,099",
            url="https://www.bestbuy.com/site/blade/newlow",
        ),
        cfg,
        store,
    )
    assert new_low.category == "match"
    assert "HISTORICAL_LOW_TIER" in new_low.triggers
    assert new_low.should_alert is True
