"""CLI entrypoint for running the laptop deal monitor locally or in GitHub Actions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from laptop_hunter.config import load_config
from laptop_hunter.dashboard import generate_dashboard
from laptop_hunter.evaluator import evaluate_all
from laptop_hunter.models import DealEvaluation
from laptop_hunter.notifier import send_discord_alerts
from laptop_hunter.providers import fetch_all_providers
from laptop_hunter.storage import StateStore, utc_now


def _write_github_output(values: dict[str, str]) -> None:
    gh_out = os.getenv("GITHUB_OUTPUT")
    if not gh_out:
        return
    with Path(gh_out).open("a", encoding="utf-8") as handle:
        for key, val in values.items():
            handle.write(f"{key}={val}\n")


def _print_deal_table(title: str, items: list[DealEvaluation], limit: int = 12) -> None:
    print(f"\n=== {title} ({len(items)}) ===")
    if not items:
        print("  (none)")
        return
    for ev in items[:limit]:
        s = ev.specs
        price = f"${s.price_usd:,.0f}" if s.price_usd is not None else "N/A"
        target = f"target ${ev.effective_target_usd:,.0f}" if ev.effective_target_usd else ""
        flags = ",".join(ev.triggers) if ev.triggers else (",".join(ev.near_miss_reasons) or "-")
        alert_mark = "[ALERT]" if ev.should_alert else "       "
        print(
            f"  {alert_mark} {price:>8} | {s.gpu or '?':<11} | "
            f"{str(s.ram_gb or '?') + 'GB':>5} | {str(s.ssd_gb or '?') + 'GB':>6} | "
            f"{s.condition:<11} | {s.store or ev.listing.provider:<12} | {flags}"
        )
        print(f"            {ev.listing.title[:105]}")
        print(f"            {ev.listing.url}")
        if target:
            print(f"            ({target})")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="laptop-hunter",
        description="Monitor gaming laptop deals, track price history, alert Discord, and build a dashboard.",
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    parser.add_argument("--state", default="data/state.json", help="Path to persistent state JSON")
    parser.add_argument("--site-dir", default="site", help="Output directory for static dashboard")
    parser.add_argument(
        "--dashboard-url",
        default=os.getenv("DASHBOARD_URL", ""),
        help="Public dashboard URL to include in Discord embed footers",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and evaluate live deals and build the dashboard without sending Discord alerts or saving state",
    )
    parser.add_argument(
        "--save-state",
        action="store_true",
        help="When combined with --dry-run, still persist updated state JSON",
    )
    parser.add_argument(
        "--dashboard-only",
        action="store_true",
        help="Regenerate the static dashboard from existing state JSON without fetching providers",
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    store = StateStore.load(args.state)
    now = utc_now()

    if args.dashboard_only:
        index_path = generate_dashboard(store, config, args.site_dir, now=now)
        print(f"Dashboard regenerated at {index_path}")
        return 0

    print("Fetching deals from enabled providers...")
    raw_listings, provider_results = fetch_all_providers(config)
    for res in provider_results:
        print(f"  [{res.status.upper():<7}] {res.provider:<13} -> {res.listing_count:>3} listings ({res.message})")

    evaluations = evaluate_all(raw_listings, config, store)
    matches = [e for e in evaluations if e.category == "match"]
    near_misses = [e for e in evaluations if e.category == "near_miss"]
    rejected = [e for e in evaluations if e.category == "rejected"]

    to_alert = [e for e in evaluations if e.should_alert][: config.alerts.max_alerts_per_run]

    print(
        f"\nEvaluation summary: {len(raw_listings)} raw -> "
        f"{len(matches)} matches, {len(near_misses)} near misses, "
        f"{len(rejected)} rejected, {len(to_alert)} alert candidate(s)."
    )

    _print_deal_table("Matched Deals (32GB+ / 1TB+)", matches)
    _print_deal_table("Near Misses & Upgradeable", near_misses, limit=8)

    state_changed = store.record_run(evaluations, provider_results, config, now=now)

    sent_alerts, alert_msg = send_discord_alerts(
        to_alert,
        dashboard_url=args.dashboard_url or None,
        dry_run=args.dry_run,
    )
    print(f"\nNotifier: {alert_msg}")

    if sent_alerts:
        store.mark_alerted(sent_alerts, now=now)
        state_changed = True

    index_path = generate_dashboard(store, config, args.site_dir, now=now)
    print(f"Dashboard generated at {index_path}")

    if not args.dry_run or args.save_state:
        store.save(args.state)
        print(f"State saved to {args.state} (meaningful change: {state_changed})")
    else:
        print("Dry-run mode: state file not modified (pass --save-state to persist).")

    _write_github_output(
        {
            "state_changed": "true" if state_changed else "false",
            "alerts_sent": str(len(sent_alerts)),
            "matches_count": str(len(matches)),
            "near_misses_count": str(len(near_misses)),
        }
    )
    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
