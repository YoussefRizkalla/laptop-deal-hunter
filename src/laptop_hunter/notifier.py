"""Discord webhook rich-embed formatter and sender."""

from __future__ import annotations

from datetime import datetime, timezone
import os
import time
from typing import Any

import httpx

from laptop_hunter.models import DealEvaluation

_CONDITION_BADGES = {
    "new": "New",
    "open_box": "Open-Box",
    "refurbished": "Certified Refurbished",
    "used": "Used",
}

_TRIGGER_LABELS = {
    "BEATS_TARGET": "Beats Target Price",
    "STEEP_DISCOUNT": "Steep Discount",
    "HISTORICAL_LOW_TIER": "All-Time Tracked GPU Low",
    "HISTORICAL_LOW_MODEL": "All-Time Tracked Model Low",
    "EXTREME_UNCONFIRMED": "Extreme Price (Verify RAM/SSD)",
}


def _embed_color(ev: DealEvaluation) -> int:
    if "HISTORICAL_LOW_TIER" in ev.triggers or "HISTORICAL_LOW_MODEL" in ev.triggers:
        return 0xF59E0B  # Gold
    if "EXTREME_UNCONFIRMED" in ev.triggers:
        return 0xF97316  # Orange
    if "BEATS_TARGET" in ev.triggers:
        return 0x10B981  # Emerald
    return 0x3B82F6  # Blue


def _format_money(amount: float | None) -> str:
    if amount is None:
        return "N/A"
    return f"${amount:,.2f}" if amount % 1 else f"${amount:,.0f}"


def _format_ssd(ssd_gb: int | None) -> str:
    if ssd_gb is None:
        return "Unconfirmed"
    if ssd_gb >= 1000 and ssd_gb % 1000 == 0:
        return f"{ssd_gb // 1000}TB SSD"
    if ssd_gb >= 1024 and ssd_gb % 1024 == 0:
        return f"{ssd_gb // 1024}TB SSD"
    return f"{ssd_gb}GB SSD"


def build_discord_embed(ev: DealEvaluation, dashboard_url: str | None = None) -> dict[str, Any]:
    """Build a single Discord rich embed dict for a DealEvaluation."""
    specs = ev.specs
    price_str = f"**{_format_money(specs.price_usd)}**"
    if specs.msrp_usd:
        price_str += f" ~~{_format_money(specs.msrp_usd)}~~"
    if specs.discount_pct:
        price_str += f" (-{specs.discount_pct:.1f}%)"

    target_note = ""
    if ev.effective_target_usd is not None and ev.price_vs_target_usd is not None:
        diff = ev.price_vs_target_usd
        sign = "-" if diff < 0 else "+"
        target_note = f"\nTarget: {_format_money(ev.effective_target_usd)} ({sign}{_format_money(abs(diff))})"
    if ev.previous_alerted_price_usd is not None and specs.price_usd is not None:
        drop = ev.previous_alerted_price_usd - specs.price_usd
        if drop > 0:
            target_note += f"\nDropped {_format_money(drop)} since last alert"

    ram_str = f"{specs.ram_gb}GB RAM" if specs.ram_gb else "Unconfirmed RAM"
    ssd_str = _format_ssd(specs.ssd_gb)
    core_specs = f"**{specs.gpu or 'Unknown GPU'}** • {ram_str} • {ssd_str}"

    display_bits = [
        f'{specs.screen_inches:g}"' if specs.screen_inches else None,
        specs.resolution,
        specs.panel_type,
        f"{specs.refresh_hz}Hz" if specs.refresh_hz else None,
    ]
    display_str = " ".join(bit for bit in display_bits if bit) or "Not specified"
    cpu_str = specs.cpu or "Not specified"

    reasons = [_TRIGGER_LABELS.get(t, t) for t in ev.triggers]
    if ev.near_miss_reasons:
        reasons.extend(ev.near_miss_reasons)
    reasons_str = " • ".join(reasons) or "Matched Deal"

    cond_label = _CONDITION_BADGES.get(specs.condition, specs.condition)
    store_label = specs.store or ev.listing.store or "Unknown Store"

    prefix = "[VERIFY SPECS] " if "EXTREME_UNCONFIRMED" in ev.triggers else ""
    title = f"{prefix}{ev.listing.title}"
    if len(title) > 250:
        title = title[:247] + "..."

    fields = [
        {"name": "Price", "value": price_str + target_note, "inline": True},
        {"name": "Condition", "value": cond_label, "inline": True},
        {"name": "Store", "value": f"{store_label} (via `{ev.listing.provider}`)", "inline": True},
        {"name": "Core Specs", "value": core_specs, "inline": False},
        {"name": "Display & CPU", "value": f"{display_str} | {cpu_str}", "inline": False},
        {"name": "Why Flagged", "value": reasons_str, "inline": False},
    ]

    footer_text = "Gaming Laptop Deal Hunter"
    if dashboard_url:
        footer_text += f" • Dashboard: {dashboard_url}"

    embed: dict[str, Any] = {
        "title": title,
        "url": ev.listing.url,
        "color": _embed_color(ev),
        "fields": fields,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": footer_text[:2000]},
    }
    if ev.listing.image_url and ev.listing.image_url.startswith("http"):
        embed["thumbnail"] = {"url": ev.listing.image_url}

    return embed


def build_discord_payloads(
    evaluations: list[DealEvaluation],
    dashboard_url: str | None = None,
) -> list[dict[str, Any]]:
    """Chunk alerts into Discord webhook payloads (max 10 embeds per message)."""
    embeds = [build_discord_embed(ev, dashboard_url=dashboard_url) for ev in evaluations]
    payloads: list[dict[str, Any]] = []
    for idx in range(0, len(embeds), 10):
        chunk = embeds[idx : idx + 10]
        header = (
            f"Found **{len(evaluations)}** killer gaming laptop deal"
            f"{'s' if len(evaluations) != 1 else ''}!"
            if idx == 0
            else None
        )
        body: dict[str, Any] = {
            "username": "Laptop Deal Hunter",
            "embeds": chunk,
        }
        if header:
            body["content"] = header
        payloads.append(body)
    return payloads


def send_discord_alerts(
    evaluations: list[DealEvaluation],
    webhook_url: str | None = None,
    dashboard_url: str | None = None,
    dry_run: bool = False,
) -> tuple[list[DealEvaluation], str]:
    """Send Discord webhook alerts for the given evaluations.

    Returns (sent_evaluations, status_message).
    """
    if not evaluations:
        return [], "No new alerts to send."

    if dry_run:
        return [], f"Dry-run: skipped sending {len(evaluations)} Discord alert(s)."

    url = (webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")).strip()
    if not url:
        return [], f"DISCORD_WEBHOOK_URL not set; skipped {len(evaluations)} alert(s)."

    payloads = build_discord_payloads(evaluations, dashboard_url=dashboard_url)
    sent_count = 0

    with httpx.Client(timeout=httpx.Timeout(15.0)) as client:
        for payload in payloads:
            resp = client.post(url, json=payload)
            if resp.status_code == 429:
                retry_after = float(resp.json().get("retry_after", 2.0))
                time.sleep(min(retry_after, 10.0))
                resp = client.post(url, json=payload)
            resp.raise_for_status()
            sent_count += len(payload["embeds"])

    return evaluations[:sent_count], f"Sent {sent_count} Discord alert(s)."
