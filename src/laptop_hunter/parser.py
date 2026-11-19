"""Deterministic laptop specification parser for unstructured deal titles and metadata."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from laptop_hunter.models import ParsedSpecs, RawListing

# Ordered from most specific to least specific so "RTX 5070 Ti" matches before "RTX 5070".
_GPU_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*5090\b", re.I), "RTX 5090"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*5080\b", re.I), "RTX 5080"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*5070[\s-]*ti\b", re.I), "RTX 5070 Ti"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*5070\b", re.I), "RTX 5070"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*5060\b", re.I), "RTX 5060"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*5050\b", re.I), "RTX 5050"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*4090\b", re.I), "RTX 4090"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*4080\b", re.I), "RTX 4080"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*4070\b", re.I), "RTX 4070"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*4060\b", re.I), "RTX 4060"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*4050\b", re.I), "RTX 4050"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*3080[\s-]*ti\b", re.I), "RTX 3080 Ti"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*3080\b", re.I), "RTX 3080"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*3070[\s-]*ti\b", re.I), "RTX 3070 Ti"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*3070\b", re.I), "RTX 3070"),
    (re.compile(r"\b(?:geforce\s+)?rtx[\s-]*3060\b", re.I), "RTX 3060"),
    (re.compile(r"\b(?:radeon\s+)?rx[\s-]*9070m\b", re.I), "RX 9070M"),
    (re.compile(r"\b(?:radeon\s+)?rx[\s-]*7900m\b", re.I), "RX 7900M"),
    (re.compile(r"\b(?:radeon\s+)?rx[\s-]*7800m\b", re.I), "RX 7800M"),
    (re.compile(r"\b(?:radeon\s+)?rx[\s-]*7700s\b", re.I), "RX 7700S"),
    (re.compile(r"\b(?:radeon\s+)?rx[\s-]*7600[ms]\b", re.I), "RX 7600S"),
]

_VALID_RAM_GB = {8, 12, 16, 24, 32, 40, 48, 64, 96, 128, 192}

_VRAM_STRIP_PATTERNS = [
    re.compile(r"\b\d{1,2}\s*GB\s*(?:GDDR\d\w*|VRAM)\b", re.I),
    # Only strip inline GPU VRAM (e.g. "RTX 5070 Ti 12GB", "RTX 5080 16GB"),
    # never system RAM like "RTX 4080 32GB DDR5" or "RTX 5070 16GB/1TB".
    re.compile(
        r"\b(?:RTX|RX)[\s-]*\d{4}(?:[\s-]*(?:Ti|M|S))?\s*\(?\s*(?:6|8|12|16|24)\s*GB\s*\)?"
        r"(?!\s*(?:(?:LP)?DDR|RAM|Memory|(?:/|\+|,)\s*\d+(?:\.\d+)?\s*(?:TB|GB)))",
        re.I,
    ),
    re.compile(r"\(\s*(?:6|8|12|16|24)\s*GB\s*(?:GDDR\d\w*|VRAM)?\s*\)", re.I),
]

_RAM_EXPLICIT_RE = re.compile(
    r"\b(?P<gb>\d{1,3})\s*GB\s*(?:(?:LP)?DDR\dX?(?:-\d{4})?\s*)?(?:RAM|Memory|Unified\s+Memory)\b"
    r"|\b(?P<gb2>\d{1,3})\s*GB\s*(?:LP)?DDR\dX?(?:-\d{4})?\b",
    re.I,
)

_RAM_SSD_PAIR_RE = re.compile(
    r"\b(?P<ram>8|12|16|24|32|48|64|96|128)\s*GB\s*(?:/|,|\+|&|-|\s+and\s+)\s*"
    r"(?P<ssd>\d+(?:\.\d+)?)\s*(?P<unit>TB|GB)\b",
    re.I,
)

_RAM_STANDALONE_RE = re.compile(
    r"\b(?P<gb>8|12|16|24|32|48|64|96|128)\s*GB\b"
    r"(?!\s*(?:SSD|NVMe|PCIe|M\.2|HDD|Storage|eMMC|UFS|GDDR|VRAM|GPU|Video))",
    re.I,
)

_SSD_EXPLICIT_RE = re.compile(
    r"\b(?:(?P<mult>[2-4])\s*x\s*)?(?P<val>\d+(?:\.\d+)?)\s*(?P<unit>TB|GB)\s*"
    r"(?:(?:PCIe(?:\s*Gen\s*\d)?|M\.2|NVMe|Gen\s*\d)\s*)*"
    r"(?:SSD|NVMe|PCIe|Solid\s*State|Storage|HDD)\b",
    re.I,
)

_SSD_TB_STANDALONE_RE = re.compile(
    r"\b(?:(?P<mult>[2-4])\s*x\s*)?(?P<val>\d+(?:\.\d+)?)\s*TB\b",
    re.I,
)

_CPU_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:Intel\s+)?Core\s+Ultra\s+[579](?:\s+\d{3}[A-Z]{0,3})?\b", re.I),
    re.compile(r"\bUltra\s+[579]\s+\d{3}[A-Z]{0,3}\b", re.I),
    re.compile(r"\b(?:Intel\s+)?(?:Core\s+)?i[579][-\s]\d{4,5}[A-Z]{1,3}\b", re.I),
    re.compile(r"\bRyzen\s+AI\s+(?:Max\+?\s+)?[579](?:\s+HX)?\s+\d{3}\b", re.I),
    re.compile(r"\bRyzen\s+[579]\s+\d{3,4}[A-Z]{1,4}\d?[A-Z]?\b", re.I),
    re.compile(r"\bRyzen\s+[579]\s+\d{3}\b", re.I),
]

_SCREEN_INCHES_RE = re.compile(
    r"\b(?P<size>1[3-8](?:\.[0-9])?)\s*(?:\"|\u2033|''|-?\s*inch(?:es)?\b)",
    re.I,
)

_PANEL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:tandem\s+)?(?:am)?oled\b", re.I), "OLED"),
    (re.compile(r"\bmini[\s-]*led\b", re.I), "Mini-LED"),
    (re.compile(r"\bips(?:[\s-]*level)?\b", re.I), "IPS"),
    (re.compile(r"\bva\s+panel\b", re.I), "VA"),
]

_RESOLUTION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(?:4K\b|UHD\+(?!\w)|UHD\b|3840\s*x\s*2(?:400|160)\b)", re.I), "4K"),
    (re.compile(r"\b(?:3\.2K|3200\s*x\s*2000)\b", re.I), "3.2K"),
    (re.compile(r"\b(?:2\.8K|2880\s*x\s*1800)\b", re.I), "2.8K"),
    (re.compile(r"\b(?:QHD\+(?!\w)|WQXGA\b|2560\s*x\s*1600\b)", re.I), "QHD+"),
    (re.compile(r"\b(?:QHD|WQHD|1440p|2560\s*x\s*1440)\b", re.I), "QHD"),
    (re.compile(r"\b(?:FHD\+(?!\w)|WUXGA\b|1920\s*x\s*1200\b)", re.I), "FHD+"),
    (re.compile(r"\b(?:FHD|1080p|1920\s*x\s*1080)\b", re.I), "FHD"),
]

_REFRESH_HZ_RE = re.compile(r"\b(?P<hz>60|90|120|144|165|180|240|300|360|480|500)\s*Hz\b", re.I)

_BRANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\balienware\b", re.I), "Alienware"),
    (re.compile(r"\b(?:asus|rog|zephyrus|strix|tuf\s+gaming)\b", re.I), "ASUS"),
    (re.compile(r"\b(?:lenovo|legion|loq|thinkpad)\b", re.I), "Lenovo"),
    (re.compile(r"\b(?:msi|raider|vector|stealth|katana|titan|pulse|crosshair|cyborg)\b", re.I), "MSI"),
    (re.compile(r"\b(?:acer|predator|helios|nitro|triton)\b", re.I), "Acer"),
    (re.compile(r"\b(?:hp|omen|victus)\b", re.I), "HP"),
    (re.compile(r"\b(?:razer|blade)\b", re.I), "Razer"),
    (re.compile(r"\b(?:gigabyte|aorus|aero)\b", re.I), "Gigabyte"),
    (re.compile(r"\bdell\b", re.I), "Dell"),
    (re.compile(r"\beluktronics\b", re.I), "Eluktronics"),
    (re.compile(r"\bframework\b", re.I), "Framework"),
    (re.compile(r"\bsamsung\b", re.I), "Samsung"),
    (re.compile(r"\blg\s+gram\b", re.I), "LG"),
]

_STORE_BRACKET_RE = re.compile(r"^\s*[\[\(]([A-Za-z0-9 &.+/'-]{2,30})[\]\)]")

_DOMAIN_STORE_MAP = {
    "bestbuy.com": "Best Buy",
    "amazon.com": "Amazon",
    "newegg.com": "Newegg",
    "bhphotovideo.com": "B&H Photo",
    "microcenter.com": "Micro Center",
    "lenovo.com": "Lenovo",
    "walmart.com": "Walmart",
    "ebay.com": "eBay",
    "antonline.com": "Antonline",
    "hp.com": "HP",
    "dell.com": "Dell",
    "asus.com": "ASUS",
    "costco.com": "Costco",
    "adorama.com": "Adorama",
    "razer.com": "Razer",
    "msi.com": "MSI",
}

_KNOWN_STORES = [
    ("best buy", "Best Buy"),
    ("bestbuy", "Best Buy"),
    ("b&h", "B&H Photo"),
    ("bhphotovideo", "B&H Photo"),
    ("micro center", "Micro Center"),
    ("microcenter", "Micro Center"),
    ("newegg", "Newegg"),
    ("amazon", "Amazon"),
    ("walmart", "Walmart"),
    ("lenovo", "Lenovo"),
    ("costco", "Costco"),
    ("ebay", "eBay"),
    ("antonline", "Antonline"),
    ("adorama", "Adorama"),
    ("dell", "Dell"),
    ("hp.com", "HP"),
    ("asus", "ASUS"),
]

_PRICE_RE = re.compile(
    r"(?P<prefix>(?:(?:save|off|was|reg\.?|msrp|list|orig\.?)\s+)|(?<!\w)-)?\$\s*"
    r"(?P<amount>\d{1,2},?\d{3}(?:\.\d{2})?|\d{3}(?:\.\d{2})?)"
    r"(?P<suffix>\s*(?:off|savings?|discount|cash\s*back|rebate))?",
    re.I,
)

_MODEL_LINE_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:ROG\s+)?(?:Zephyrus|Strix\s+SCAR|Strix\s+G|TUF\s+Gaming)\s+[A-Z]?\d{2,3}\b", re.I),
    re.compile(r"\bLegion\s+(?:Pro\s+|Slim\s+)?[579]i?(?:\s+Gen\s+\d{1,2})?\b", re.I),
    re.compile(r"\b(?:Raider|Vector|Stealth|Titan|Katana|Pulse|Crosshair)\s+[A-Z]?\d{2}[A-Z]{0,3}\b", re.I),
    re.compile(r"\bPredator\s+Helios\s+(?:Neo\s+)?\d{2}[A-Z]?\b", re.I),
    re.compile(r"\bOMEN\s+(?:MAX\s+|Transcend\s+)?\d{2}\b", re.I),
    re.compile(r"\bAlienware\s+(?:m|x|Area-51)\s*\d{2}(?:\s*R\d)?\b", re.I),
    re.compile(r"\bRazer\s+Blade\s+\d{2}\b", re.I),
    re.compile(r"\bAORUS\s+(?:Master\s+)?\d{2}[A-Z]?\b", re.I),
]


def extract_gpu(text: str) -> str | None:
    """Extract canonical GPU name from text."""
    for pattern, canonical in _GPU_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def _strip_vram(text: str) -> str:
    cleaned = text
    for pat in _VRAM_STRIP_PATTERNS:
        cleaned = pat.sub(" ", cleaned)
    return cleaned


def extract_ram_gb(text: str) -> int | None:
    """Extract system RAM in GB while ignoring GPU VRAM and SSD sizes."""
    cleaned = _strip_vram(text)

    match = _RAM_EXPLICIT_RE.search(cleaned)
    if match:
        val = int(match.group("gb") or match.group("gb2"))
        if val in _VALID_RAM_GB:
            return val

    pair = _RAM_SSD_PAIR_RE.search(cleaned)
    if pair:
        val = int(pair.group("ram"))
        if val in _VALID_RAM_GB:
            return val

    for standalone in _RAM_STANDALONE_RE.finditer(cleaned):
        val = int(standalone.group("gb"))
        if val in _VALID_RAM_GB:
            return val

    return None


def _to_gb(val_str: str, unit: str, mult_str: str | None = None) -> int:
    val = float(val_str)
    mult = int(mult_str) if mult_str else 1
    if unit.upper() == "TB":
        return int(round(val * 1000 * mult))
    return int(round(val * mult))


def extract_ssd_gb(text: str) -> int | None:
    """Extract primary SSD storage capacity in GB (1TB normalized to 1000GB)."""
    match = _SSD_EXPLICIT_RE.search(text)
    if match:
        gb = _to_gb(match.group("val"), match.group("unit"), match.group("mult"))
        if gb >= 256:
            return gb

    pair = _RAM_SSD_PAIR_RE.search(text)
    if pair:
        gb = _to_gb(pair.group("ssd"), pair.group("unit"))
        if gb >= 256:
            return gb

    tb_match = _SSD_TB_STANDALONE_RE.search(text)
    if tb_match:
        gb = _to_gb(tb_match.group("val"), "TB", tb_match.group("mult"))
        if gb >= 500:
            return gb

    return None


def extract_cpu(text: str) -> str | None:
    for pattern in _CPU_PATTERNS:
        match = pattern.search(text)
        if match:
            return re.sub(r"\s+", " ", match.group(0)).strip()
    return None


def extract_screen_inches(text: str) -> float | None:
    match = _SCREEN_INCHES_RE.search(text)
    if match:
        size = float(match.group("size"))
        if 13.0 <= size <= 18.5:
            return size
    return None


def extract_panel_type(text: str) -> str | None:
    for pattern, canonical in _PANEL_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def extract_resolution(text: str) -> str | None:
    for pattern, canonical in _RESOLUTION_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def extract_refresh_hz(text: str) -> int | None:
    match = _REFRESH_HZ_RE.search(text)
    if match:
        return int(match.group("hz"))
    return None


def extract_brand(text: str) -> str | None:
    for pattern, canonical in _BRANDS:
        if pattern.search(text):
            return canonical
    return None


def extract_model_name(text: str, brand: str | None = None) -> str | None:
    for pattern in _MODEL_LINE_PATTERNS:
        match = pattern.search(text)
        if match:
            name = re.sub(r"\s+", " ", match.group(0)).strip()
            if brand and brand.lower() not in name.lower():
                return f"{brand} {name}"
            return name
    return brand


def extract_condition(text: str, hint: str | None = None) -> str:
    combined = f"{hint or ''} {text}".lower()
    if re.search(r"\bopen[\s-]*box\b", combined):
        return "open_box"
    if re.search(
        r"\b(?:certified\s+refurb|manufacturer\s+refurb|factory\s+refurb|refurbished|refurb|recertified|renewed|lenovo\s+outlet)\b",
        combined,
    ):
        return "refurbished"
    if re.search(r"\b(?:used|pre-?owned|second-?hand|for\s+parts)\b", combined):
        return "used"
    return "new"


def extract_store(title: str, url: str, existing_store: str | None = None) -> str | None:
    if existing_store:
        return existing_store.strip()

    bracket = _STORE_BRACKET_RE.match(title)
    if bracket:
        candidate = bracket.group(1).strip()
        lower_cand = candidate.lower()
        for needle, canonical in _KNOWN_STORES:
            if needle in lower_cand:
                return canonical
        # Accept short bracket store tags if not a condition/flair tag
        if lower_cand not in {"us", "usa", "deal", "sale", "refurb", "open box", "expired"}:
            return candidate

    try:
        host = (urlparse(url).hostname or "").lower()
        for domain, canonical in _DOMAIN_STORE_MAP.items():
            if host == domain or host.endswith(f".{domain}"):
                return canonical
    except Exception:
        pass

    lower_title = title.lower()
    for needle, canonical in _KNOWN_STORES:
        if f"at {needle}" in lower_title or f"from {needle}" in lower_title or f"via {needle}" in lower_title:
            return canonical

    return None


def extract_prices(text: str) -> tuple[float | None, float | None]:
    """Extract (sale_price_usd, msrp_usd) from unstructured deal text."""
    sale_candidates: list[float] = []
    msrp_candidates: list[float] = []
    savings_amount: float | None = None

    for match in _PRICE_RE.finditer(text):
        raw_amount = float(match.group("amount").replace(",", ""))
        prefix = (match.group("prefix") or "").strip().lower()
        suffix = (match.group("suffix") or "").strip().lower()

        is_savings = (
            prefix.startswith(("save", "off", "-"))
            or bool(suffix)
        )
        is_msrp = prefix.startswith(("was", "reg", "msrp", "list", "orig"))

        if is_savings:
            if 50 <= raw_amount <= 3000:
                savings_amount = raw_amount
            continue

        if is_msrp:
            if 500 <= raw_amount <= 9000:
                msrp_candidates.append(raw_amount)
            continue

        if 400 <= raw_amount <= 8500:
            sale_candidates.append(raw_amount)

    sale_price = sale_candidates[0] if sale_candidates else None
    msrp = msrp_candidates[0] if msrp_candidates else None

    # If multiple unlabeled prices exist (e.g. "$1,499 $1,999"), lower is sale, higher is MSRP
    if sale_price is not None and msrp is None and len(sale_candidates) >= 2:
        low, high = min(sale_candidates[:2]), max(sale_candidates[:2])
        if high > low * 1.05:
            sale_price = low
            msrp = high

    if sale_price is not None and msrp is None and savings_amount is not None:
        msrp = round(sale_price + savings_amount, 2)

    if sale_price is not None and msrp is not None and msrp <= sale_price:
        msrp = None

    return sale_price, msrp


def _int_or_none(val: object) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def parse_listing(listing: RawListing) -> ParsedSpecs:
    """Parse structured specifications from a RawListing."""
    title = listing.title or ""
    desc = listing.description or ""
    combined = f"{title}\n{desc}".strip()
    raw = listing.raw_specs or {}

    gpu = raw.get("gpu") or extract_gpu(title) or extract_gpu(desc)
    ram_gb = _int_or_none(raw.get("ram_gb")) or extract_ram_gb(title) or extract_ram_gb(desc)
    ssd_gb = _int_or_none(raw.get("ssd_gb")) or extract_ssd_gb(title) or extract_ssd_gb(desc)
    cpu = raw.get("cpu") or extract_cpu(title) or extract_cpu(desc)
    brand = raw.get("brand") or extract_brand(title) or extract_brand(desc)
    model_name = raw.get("model_name") or extract_model_name(title, brand=brand)
    screen_inches = raw.get("screen_inches") or extract_screen_inches(title) or extract_screen_inches(desc)
    panel_type = raw.get("panel_type") or extract_panel_type(title) or extract_panel_type(desc)
    resolution = raw.get("resolution") or extract_resolution(title) or extract_resolution(desc)
    refresh_hz = _int_or_none(raw.get("refresh_hz")) or extract_refresh_hz(title) or extract_refresh_hz(desc)
    condition = extract_condition(combined, hint=listing.condition_hint)
    store = extract_store(title, listing.url, existing_store=listing.store)

    parsed_price, parsed_msrp = extract_prices(title)
    if parsed_price is None and desc:
        parsed_price, desc_msrp = extract_prices(desc)
        if parsed_msrp is None:
            parsed_msrp = desc_msrp

    price_usd = listing.price_usd if listing.price_usd is not None else parsed_price
    msrp_usd = listing.msrp_usd if listing.msrp_usd is not None else parsed_msrp

    if price_usd is not None and msrp_usd is not None and msrp_usd <= price_usd:
        msrp_usd = None

    discount_pct: float | None = None
    if price_usd is not None and msrp_usd is not None and msrp_usd > price_usd:
        discount_pct = round(((msrp_usd - price_usd) / msrp_usd) * 100.0, 1)

    return ParsedSpecs(
        gpu=gpu,
        ram_gb=ram_gb,
        ssd_gb=ssd_gb,
        cpu=cpu,
        brand=brand,
        model_name=model_name,
        screen_inches=float(screen_inches) if screen_inches is not None else None,
        panel_type=panel_type,
        resolution=resolution,
        refresh_hz=refresh_hz,
        condition=condition,
        price_usd=round(float(price_usd), 2) if price_usd is not None else None,
        msrp_usd=round(float(msrp_usd), 2) if msrp_usd is not None else None,
        store=store,
        discount_pct=discount_pct,
    )
