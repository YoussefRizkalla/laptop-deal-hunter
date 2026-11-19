"""Unit tests for Discord webhook rich-embed formatting and batching."""

from pathlib import Path

from laptop_hunter.config import load_config
from laptop_hunter.evaluator import evaluate_listing
from laptop_hunter.models import RawListing
from laptop_hunter.notifier import build_discord_embed, build_discord_payloads
from laptop_hunter.storage import StateStore

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_build_discord_embed_structure() -> None:
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = StateStore()
    listing = RawListing(
        provider="reddit",
        external_id="r1",
        title='[Best Buy] ASUS ROG Zephyrus G16 16" OLED 240Hz RTX 5070 Ti 32GB 2TB SSD - $1,449 (was $2,199)',
        url="https://www.bestbuy.com/site/g16/123",
        image_url="https://example.com/laptop.jpg",
    )
    ev = evaluate_listing(listing, cfg, store)
    embed = build_discord_embed(ev, dashboard_url="https://user.github.io/laptop-deal-hunter/")

    assert embed["url"] == "https://www.bestbuy.com/site/g16/123"
    assert embed["color"] == 0x10B981
    assert embed["thumbnail"]["url"] == "https://example.com/laptop.jpg"
    field_map = {f["name"]: f["value"] for f in embed["fields"]}
    assert "$1,449" in field_map["Price"]
    assert "RTX 5070 Ti" in field_map["Core Specs"]
    assert "32GB RAM" in field_map["Core Specs"]
    assert "2TB SSD" in field_map["Core Specs"]
    assert "OLED" in field_map["Display & CPU"]
    assert "Beats Target Price" in field_map["Why Flagged"]


def test_payload_batching_respects_10_embed_limit() -> None:
    cfg = load_config(REPO_ROOT / "config.yaml")
    store = StateStore()
    evals = [
        evaluate_listing(
            RawListing(
                provider="reddit",
                external_id=f"r{i}",
                title=f"[Best Buy] Legion Pro RTX 5070 32GB 1TB SSD - ${1100 + i}",
                url=f"https://www.bestbuy.com/site/legion/{i}",
            ),
            cfg,
            store,
        )
        for i in range(12)
    ]
    payloads = build_discord_payloads(evals)
    assert len(payloads) == 2
    assert len(payloads[0]["embeds"]) == 10
    assert len(payloads[1]["embeds"]) == 2
    assert "Found **12**" in payloads[0]["content"]
