"""Deal evaluation engine: spec filtering, target pricing, historical lows, and anti-spam."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from laptop_hunter.config import AppConfig
from laptop_hunter.models import DealEvaluation, ParsedSpecs, RawListing
from laptop_hunter.parser import parse_listing
from laptop_hunter.storage import StateStore

_TRACKING_PARAM_PREFIXES = ("utm_", "ref", "tag", "ascsubtag", "irclickid", "irgwc", "clickid", "fbclid", "gclid")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    return _SLUG_RE.sub("-", value.lower()).strip("-")


def normalize_url(url: str) -> str:
    """Strip affiliate/tracking query parameters for reliable cross-source deduplication."""
    try:
        parsed = urlparse(url.strip())
        clean_params = [
            (k, v)
            for k, v in parse_qsl(parsed.query, keep_blank_values=False)
            if not k.lower().startswith(_TRACKING_PARAM_PREFIXES)
        ]
        host = (parsed.hostname or "").lower().removeprefix("www.")
        path = parsed.path.rstrip("/")
        return urlunparse((parsed.scheme.lower() or "https", host, path, "", urlencode(clean_params), ""))
    except Exception:
        return url.strip().lower()


def make_deal_id(listing: RawListing, specs: ParsedSpecs) -> str:
    """Create a deterministic ID for deduplicating a deal across runs and providers."""
    if listing.sku and specs.store:
        raw_key = f"sku:{_slugify(specs.store)}:{listing.sku}:{specs.condition}"
    else:
        norm_url = normalize_url(listing.url)
        raw_key = f"url:{norm_url}|{specs.condition}"
    return hashlib.sha1(raw_key.encode("utf-8")).hexdigest()[:16]


def make_model_key(specs: ParsedSpecs) -> str:
    """Create a canonical model key for tracking historical lows of a specific laptop tier."""
    model = _slugify(specs.model_name or specs.brand or "unknown")
    gpu = _slugify(specs.gpu or "unknown")
    ram = f"{specs.ram_gb}gb" if specs.ram_gb else "unkram"
    return f"{model}|{gpu}|{ram}|{specs.condition}"


def _passes_redrop_threshold(
    new_price: float,
    previous_alerted_price: float | None,
    config: AppConfig,
) -> bool:
    if previous_alerted_price is None:
        return True
    drop_usd = previous_alerted_price - new_price
    if drop_usd <= 0:
        return False
    drop_pct = (drop_usd / previous_alerted_price) * 100.0
    return drop_usd >= config.alerts.min_redrop_usd or drop_pct >= config.alerts.min_redrop_pct


def evaluate_listing(
    listing: RawListing,
    config: AppConfig,
    store: StateStore,
) -> DealEvaluation:
    """Parse and evaluate a single RawListing against config rules and price history."""
    specs = parse_listing(listing)
    deal_id = make_deal_id(listing, specs)
    model_key = make_model_key(specs)

    title_lower = (listing.title or "").lower()

    # 1. Keyword exclusions (desktops, GPUs, monitors, etc.)
    for kw in config.specs.exclude_keywords:
        if kw and kw in title_lower:
            return DealEvaluation(
                deal_id=deal_id,
                model_key=model_key,
                listing=listing,
                specs=specs,
                category="rejected",
                rejection_reason=f"Excluded keyword: {kw}",
            )

    # 2. Brand exclusions
    if specs.brand and specs.brand.lower() in config.specs.exclude_brands:
        return DealEvaluation(
            deal_id=deal_id,
            model_key=model_key,
            listing=listing,
            specs=specs,
            category="rejected",
            rejection_reason=f"Excluded brand: {specs.brand}",
        )

    # 3. Require valid price
    if specs.price_usd is None or specs.price_usd <= 0:
        return DealEvaluation(
            deal_id=deal_id,
            model_key=model_key,
            listing=listing,
            specs=specs,
            category="rejected",
            rejection_reason="No valid price detected",
        )

    # 4. Require target GPU (RTX 5070 or equivalent and higher)
    gpu_target = config.get_gpu_target(specs.gpu)
    if gpu_target is None:
        return DealEvaluation(
            deal_id=deal_id,
            model_key=model_key,
            listing=listing,
            specs=specs,
            category="rejected",
            rejection_reason=f"GPU below target or undetected ({specs.gpu or 'none'})",
        )

    # 5. Condition filter
    if specs.condition not in config.conditions.allowed:
        return DealEvaluation(
            deal_id=deal_id,
            model_key=model_key,
            listing=listing,
            specs=specs,
            category="rejected",
            rejection_reason=f"Condition not allowed: {specs.condition}",
        )

    # 6. Optional hard ceiling
    if config.specs.max_price_usd is not None and specs.price_usd > config.specs.max_price_usd:
        return DealEvaluation(
            deal_id=deal_id,
            model_key=model_key,
            listing=listing,
            specs=specs,
            category="rejected",
            rejection_reason=f"Exceeds hard budget ceiling (${config.specs.max_price_usd:,.0f})",
        )

    # Compute effective target price (stricter for open-box / refurbished)
    effective_target = gpu_target.target_price_usd
    if specs.condition != "new":
        effective_target = round(effective_target * config.conditions.non_new_price_multiplier, 2)

    price_vs_target = round(specs.price_usd - effective_target, 2)

    # 7. Check RAM and SSD strictness (match vs near_miss)
    near_miss_reasons: list[str] = []
    explicit_spec_shortfall = False

    if specs.ram_gb is None:
        near_miss_reasons.append("RAM unconfirmed in title")
    elif specs.ram_gb < config.specs.min_ram_gb:
        near_miss_reasons.append(f"{specs.ram_gb}GB RAM (< {config.specs.min_ram_gb}GB, upgradeable)")
        explicit_spec_shortfall = True

    if specs.ssd_gb is None:
        near_miss_reasons.append("SSD unconfirmed in title")
    elif specs.ssd_gb < config.specs.min_ssd_gb:
        near_miss_reasons.append(f"{specs.ssd_gb}GB SSD (< {config.specs.min_ssd_gb}GB, upgradeable)")
        explicit_spec_shortfall = True

    category = "match" if not near_miss_reasons else "near_miss"

    # 8. Evaluate "Can't Be Beat" triggers
    triggers: list[str] = []
    tier_low, tier_samples = store.get_gpu_tier_low(specs.gpu or "", condition=specs.condition)
    model_low, model_samples = store.get_model_low(model_key)
    historical_low = model_low if model_low is not None else tier_low

    if category == "match":
        if specs.price_usd <= effective_target:
            triggers.append("BEATS_TARGET")

        if (
            specs.discount_pct is not None
            and specs.discount_pct >= config.alerts.min_steep_discount_pct
            and specs.price_usd <= effective_target * config.alerts.steep_discount_max_target_ratio
        ):
            triggers.append("STEEP_DISCOUNT")

        if config.alerts.alert_on_historical_low:
            min_samples = config.alerts.historical_low_min_samples
            if tier_low is not None and tier_samples >= min_samples and specs.price_usd < tier_low:
                triggers.append("HISTORICAL_LOW_TIER")
            if model_low is not None and model_samples >= min_samples and specs.price_usd < model_low:
                triggers.append("HISTORICAL_LOW_MODEL")
    else:
        # Near miss: NEVER ping Discord if RAM/SSD is explicitly below minimum.
        # Only ping if RAM/SSD were simply omitted from a terse title AND price is an extreme outlier.
        if (
            not explicit_spec_shortfall
            and config.alerts.alert_unconfirmed_specs_if_extreme
            and specs.price_usd <= round(effective_target * config.alerts.unconfirmed_extreme_price_ratio, 2)
        ):
            triggers.append("EXTREME_UNCONFIRMED")

    # 9. Anti-spam deduplication
    prev_alerted = store.get_previous_alerted_price(deal_id)
    should_alert = bool(triggers) and _passes_redrop_threshold(specs.price_usd, prev_alerted, config)

    # 10. Compute priority score for ranking alerts and dashboard cards
    priority = 0
    if "HISTORICAL_LOW_TIER" in triggers:
        priority += 50
    if "HISTORICAL_LOW_MODEL" in triggers:
        priority += 35
    if "BEATS_TARGET" in triggers:
        pct_under = max(0.0, (effective_target - specs.price_usd) / effective_target * 100.0)
        priority += 40 + int(pct_under * 2)
    if "STEEP_DISCOUNT" in triggers and specs.discount_pct:
        priority += int(specs.discount_pct)
    if "EXTREME_UNCONFIRMED" in triggers:
        priority += 30
    if specs.panel_type in ("OLED", "Mini-LED"):
        priority += 5
    priority += gpu_target.tier * 3

    return DealEvaluation(
        deal_id=deal_id,
        model_key=model_key,
        listing=listing,
        specs=specs,
        category=category,
        near_miss_reasons=near_miss_reasons,
        effective_target_usd=effective_target,
        triggers=triggers,
        should_alert=should_alert,
        alert_priority=priority,
        price_vs_target_usd=price_vs_target,
        historical_low_usd=historical_low,
        previous_alerted_price_usd=prev_alerted,
    )


def _spec_richness(ev: DealEvaluation) -> tuple[int, int, float]:
    """Score used to pick the best duplicate when multiple sources list the exact same deal."""
    cat_rank = 2 if ev.category == "match" else (1 if ev.category == "near_miss" else 0)
    filled = sum(
        1
        for val in (
            ev.specs.gpu,
            ev.specs.ram_gb,
            ev.specs.ssd_gb,
            ev.specs.cpu,
            ev.specs.screen_inches,
            ev.specs.panel_type,
            ev.specs.msrp_usd,
        )
        if val is not None
    )
    neg_price = -(ev.specs.price_usd or 999999.0)
    return (cat_rank, filled, neg_price)


def evaluate_all(
    listings: list[RawListing],
    config: AppConfig,
    store: StateStore,
) -> list[DealEvaluation]:
    """Evaluate all listings and deduplicate identical deals across providers."""
    best_by_id: dict[str, DealEvaluation] = {}
    rejected: list[DealEvaluation] = []

    for listing in listings:
        ev = evaluate_listing(listing, config, store)
        if ev.category == "rejected":
            rejected.append(ev)
            continue

        existing = best_by_id.get(ev.deal_id)
        if existing is None or _spec_richness(ev) > _spec_richness(existing):
            best_by_id[ev.deal_id] = ev

    active = sorted(
        best_by_id.values(),
        key=lambda e: (
            0 if e.category == "match" else 1,
            -e.alert_priority,
            e.specs.price_usd or 999999.0,
        ),
    )
    return active + rejected
