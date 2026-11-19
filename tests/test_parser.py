"""Comprehensive tests for deterministic laptop spec parsing."""

import pytest

from laptop_hunter.models import RawListing
from laptop_hunter.parser import parse_listing


def _make_listing(title: str, url: str = "https://www.bestbuy.com/site/123", **kwargs) -> RawListing:
    return RawListing(
        provider="reddit",
        external_id="abc123",
        title=title,
        url=url,
        **kwargs,
    )


def test_parse_rich_reddit_title() -> None:
    listing = _make_listing(
        '[Best Buy] ASUS ROG Zephyrus G16: 16" QHD+ OLED 240Hz, Core Ultra 9 285HX, '
        "RTX 5070 Ti 12GB GDDR7, 32GB LPDDR5X, 2TB NVMe SSD - $1,549.99 (was $2,199.99)"
    )
    specs = parse_listing(listing)
    assert specs.gpu == "RTX 5070 Ti"
    assert specs.ram_gb == 32
    assert specs.ssd_gb == 2000
    assert specs.cpu == "Core Ultra 9 285HX"
    assert specs.brand == "ASUS"
    assert specs.model_name == "ASUS ROG Zephyrus G16"
    assert specs.screen_inches == pytest.approx(16.0)
    assert specs.panel_type == "OLED"
    assert specs.resolution == "QHD+"
    assert specs.refresh_hz == 240
    assert specs.condition == "new"
    assert specs.store == "Best Buy"
    assert specs.price_usd == pytest.approx(1549.99)
    assert specs.msrp_usd == pytest.approx(2199.99)
    assert specs.discount_pct == pytest.approx(29.5)


def test_vram_is_not_confused_with_system_ram() -> None:
    listing = _make_listing(
        "[Lenovo] Legion Pro 7i: 16\" WQXGA 240Hz, RTX 5080 16GB GDDR7, 32GB/1TB - $1,949"
    )
    specs = parse_listing(listing)
    assert specs.gpu == "RTX 5080"
    assert specs.ram_gb == 32
    assert specs.ssd_gb == 1000
    assert specs.price_usd == pytest.approx(1949.0)


def test_vram_only_title_leaves_ram_none() -> None:
    listing = _make_listing(
        "[B&H] MSI Vector 16 HX: RTX 5070 Ti 12GB, Ultra 7 255H - $1,399 (Save $400)",
        url="https://www.bhphotovideo.com/c/product/123",
    )
    specs = parse_listing(listing)
    assert specs.gpu == "RTX 5070 Ti"
    assert specs.ram_gb is None
    assert specs.ssd_gb is None
    assert specs.price_usd == pytest.approx(1399.0)
    assert specs.msrp_usd == pytest.approx(1799.0)
    assert specs.store == "B&H Photo"


def test_open_box_and_refurbished_conditions() -> None:
    open_box = parse_listing(
        _make_listing("Open-Box Excellent: Acer Predator Helios 16 RTX 5070 32GB 1TB - $1,099")
    )
    assert open_box.condition == "open_box"
    assert open_box.brand == "Acer"

    open_boxes = parse_listing(
        _make_listing("Open Boxes: GIGABYTE GAMING A16 RTX 5070 32GB 1TB - $1,134")
    )
    assert open_boxes.condition == "open_box"

    refurb = parse_listing(
        _make_listing("Certified Refurbished Lenovo Legion Pro 5 RTX 4080 32GB DDR5 2TB SSD $1,349")
    )
    assert refurb.condition == "refurbished"
    assert refurb.gpu == "RTX 4080"
    assert refurb.ram_gb == 32
    assert refurb.ssd_gb == 2000

    used = parse_listing(
        _make_listing("Used Razer Blade 16 RTX 5090 64GB RAM 2TB SSD $2,100")
    )
    assert used.condition == "used"


def test_multi_drive_ssd_and_amd_ryzen_cpu() -> None:
    listing = _make_listing(
        "[Newegg] MSI Raider 18 HX: 18\" 4K Mini-LED 120Hz, Ryzen 9 9955HX3D, RTX 5090, 64GB DDR5, 2x2TB NVMe - $2,599",
        url="https://www.newegg.com/p/123",
    )
    specs = parse_listing(listing)
    assert specs.gpu == "RTX 5090"
    assert specs.ram_gb == 64
    assert specs.ssd_gb == 4000
    assert specs.cpu == "Ryzen 9 9955HX3D"
    assert specs.screen_inches == pytest.approx(18.0)
    assert specs.panel_type == "Mini-LED"
    assert specs.resolution == "4K"
    assert specs.refresh_hz == 120
    assert specs.store == "Newegg"


def test_discount_amount_not_mistaken_for_price() -> None:
    listing = _make_listing(
        "[Lenovo] Save $500 on Legion 7i RTX 5070 32GB RAM 1TB SSD - $1,199",
        url="https://www.lenovo.com/us/en/p/123",
    )
    specs = parse_listing(listing)
    assert specs.price_usd == pytest.approx(1199.0)
    assert specs.msrp_usd == pytest.approx(1699.0)
    assert specs.discount_pct == pytest.approx(29.4)


def test_url_slug_rescues_ram_ssd_and_store_from_terse_slickdeals_title() -> None:
    listing = _make_listing(
        "Lenovo Legion Pro 7i Laptop: 16\" 1600p 240Hz OLED, Intel Ultra 9 275HX, RTX 5090 $2750 + Free Shipping",
        url=(
            "https://slickdeals.net/f/19017115-lenovo-legion-pro-7i-16-qhd-240hz-oled-"
            "intel-ultra-9-275hx-rtx-5090-32gb-ddr5-2tb-ssd-2749-bestbuy-com"
        ),
    )
    specs = parse_listing(listing)
    assert specs.gpu == "RTX 5090"
    assert specs.ram_gb == 32
    assert specs.ssd_gb == 2000
    assert specs.store == "Best Buy"
