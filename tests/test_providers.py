"""Unit tests for all deal provider parsers using realistic fixtures."""

from datetime import datetime, timezone

import pytest

from laptop_hunter.providers.bestbuy import parse_bestbuy_open_box, parse_bestbuy_products
from laptop_hunter.providers.dealnews import parse_dealnews_rss
from laptop_hunter.providers.gaminglaptop import parse_gaminglaptop_html
from laptop_hunter.providers.reddit import (
    parse_arctic_shift_json,
    parse_reddit_json,
    parse_reddit_rss,
)
from laptop_hunter.providers.slickdeals import parse_slickdeals_rss


def test_parse_reddit_json_skips_expired_and_extracts_merchant_url() -> None:
    payload = {
        "data": {
            "children": [
                {
                    "data": {
                        "id": "p1",
                        "title": "[Best Buy] ASUS ROG Strix G16 RTX 5070 Ti 32GB 1TB - $1,499",
                        "url": "https://www.bestbuy.com/site/strix-g16/12345.p",
                        "permalink": "/r/LaptopDeals/comments/p1/asus/",
                        "selftext": "",
                        "link_flair_text": "US",
                        "score": 88,
                        "created_utc": 1763500000,
                    }
                },
                {
                    "data": {
                        "id": "p2",
                        "title": "[Amazon] Expired RTX 5080 Laptop - $1,699",
                        "url": "https://www.amazon.com/dp/B000000",
                        "permalink": "/r/LaptopDeals/comments/p2/expired/",
                        "selftext": "",
                        "link_flair_text": "Expired",
                        "score": 120,
                    }
                },
                {
                    "data": {
                        "id": "p3",
                        "title": "[Request] Need a laptop for college",
                        "url": "https://www.reddit.com/r/LaptopDeals/comments/p3/",
                        "permalink": "/r/LaptopDeals/comments/p3/",
                        "selftext": "Budget $1000",
                        "link_flair_text": "Request",
                    }
                },
            ]
        }
    }
    listings = parse_reddit_json(payload, "LaptopDeals")
    assert len(listings) == 1
    assert listings[0].external_id == "LaptopDeals:p1"
    assert listings[0].url == "https://www.bestbuy.com/site/strix-g16/12345.p"
    assert listings[0].upvotes == 88


def test_parse_reddit_rss_fallback() -> None:
    rss = """<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <id>t3_xyz</id>
        <title>[B&amp;H] Lenovo Legion Pro 7i RTX 5080 32GB 2TB - $1,899</title>
        <link href="https://www.reddit.com/r/LaptopDeals/comments/xyz/" />
        <updated>2026-11-18T12:00:00+00:00</updated>
        <content type="html">&lt;a href="https://www.bhphotovideo.com/c/product/999"&gt;[link]&lt;/a&gt;</content>
      </entry>
    </feed>
    """
    listings = parse_reddit_rss(rss, "LaptopDeals")
    assert len(listings) == 1
    assert listings[0].url == "https://www.bhphotovideo.com/c/product/999"
    assert "Legion Pro 7i" in listings[0].title


def test_parse_arctic_shift_json() -> None:
    payload = {
        "data": [
            {
                "id": "as1",
                "title": "[Amazon] GIGABYTE AERO X16 RTX 5070 32GB DDR5 1TB SSD. Now: $1,199 After 28% Off",
                "url": "https://www.amazon.com/dp/B0TEST",
                "permalink": "/r/LaptopDeals/comments/as1/aero/",
                "selftext": "",
                "score": 12,
                "created_utc": 1795140890,
            },
            {
                "id": "as2",
                "title": "Expired deal",
                "url": "https://www.amazon.com/dp/B0OLD",
                "link_flair_text": "Expired",
            },
        ]
    }
    listings = parse_arctic_shift_json(payload, "LaptopDeals")
    assert len(listings) == 1
    assert listings[0].external_id == "LaptopDeals:as1"
    assert listings[0].url == "https://www.amazon.com/dp/B0TEST"


def test_reddit_provider_supports_title_filter_subreddit_dict() -> None:
    import httpx
    from laptop_hunter.providers.reddit import RedditProvider

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("subreddit") == "buildapcsales"
        assert "title" not in request.url.params
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "b1",
                        "title": "[Laptop] ASUS ROG Strix RTX 5070 Ti 32GB 1TB - $1,499",
                        "url": "https://www.bestbuy.com/site/strix/1",
                        "permalink": "/r/buildapcsales/comments/b1/",
                        "created_utc": datetime.now(timezone.utc).timestamp(),
                    },
                    {
                        "id": "b2",
                        "title": "[GPU] RTX 5070 Ti Desktop Card - $749",
                        "url": "https://www.newegg.com/p/gpu",
                        "permalink": "/r/buildapcsales/comments/b2/",
                        "created_utc": datetime.now(timezone.utc).timestamp(),
                    },
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    listings, result = RedditProvider().fetch(
        client,
        {
            "subreddits": [{"name": "buildapcsales", "title_filter": "laptop", "limit": 20}],
            "max_post_age_days": 14,
        },
    )
    assert result.status == "ok"
    assert len(listings) == 1
    assert "ASUS ROG Strix" in listings[0].title


def test_parse_slickdeals_rss() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>Lenovo Legion Pro 5: 16" QHD+ 240Hz, RTX 5070, 32GB RAM, 1TB SSD $1,199</title>
        <link>https://slickdeals.net/f/17890001-lenovo-legion</link>
        <guid>https://slickdeals.net/f/17890001</guid>
        <pubDate>Wed, 18 Nov 2026 18:00:00 GMT</pubDate>
        <description><![CDATA[<img src="https://static.slickdealscdn.com/img.jpg"/> Great deal at Lenovo.]]></description>
      </item>
      <item>
        <title>Ancient Deal RTX 5070 32GB 1TB $999</title>
        <link>https://slickdeals.net/f/10000001-old</link>
        <guid>https://slickdeals.net/f/10000001</guid>
        <pubDate>Mon, 01 Jan 2026 12:00:00 GMT</pubDate>
        <description>Expired archive entry</description>
      </item>
    </channel></rss>
    """
    now = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)
    listings = parse_slickdeals_rss(xml, max_age_days=14, now=now)
    assert len(listings) == 1
    assert listings[0].provider == "slickdeals"
    assert listings[0].image_url == "https://static.slickdealscdn.com/img.jpg"
    assert "Great deal at Lenovo." in listings[0].description


def test_parse_dealnews_rss() -> None:
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0"><channel>
      <item>
        <title>ASUS ROG Strix G16 RTX 5070 Ti 32GB RAM 1TB SSD Gaming Laptop for $1,449</title>
        <link>https://www.dealnews.com/products/ASUS-ROG-Strix/123.html</link>
        <guid>dn-123</guid>
        <pubDate>Wed, 18 Nov 2026 16:00:00 GMT</pubDate>
        <description>Lowest price ever at Best Buy.</description>
      </item>
    </channel></rss>
    """
    now = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)
    listings = parse_dealnews_rss(xml, max_age_days=14, now=now)
    assert len(listings) == 1
    assert listings[0].provider == "dealnews"
    assert "RTX 5070 Ti" in listings[0].title


def test_parse_gaminglaptop_html_cards() -> None:
    html = """
    <html><body>
      <article class="deal-card">
        <h3>ASUS ROG Zephyrus G16 (2026)</h3>
        <p>16" OLED 240Hz, RTX 5070 Ti, 32GB RAM, 2TB SSD - $1,549.99 (was $2,099.99)</p>
        <a href="https://www.bestbuy.com/site/zephyrus/999">Buy at Best Buy</a>
      </article>
      <article class="deal-card">
        <h3>Random Gaming Mouse</h3>
        <p>$49.99</p>
        <a href="https://www.amazon.com/mouse">Buy</a>
      </article>
    </body></html>
    """
    listings = parse_gaminglaptop_html(html)
    assert len(listings) == 1
    assert listings[0].price_usd == pytest.approx(1549.99)
    assert listings[0].msrp_usd == pytest.approx(2099.99)
    assert listings[0].url == "https://www.bestbuy.com/site/zephyrus/999"


def test_parse_bestbuy_products_and_open_box() -> None:
    products_payload = {
        "products": [
            {
                "sku": 6599123,
                "name": 'ASUS - ROG Strix G16 16" QHD+ 240Hz Gaming Laptop - RTX 5080',
                "salePrice": 1949.99,
                "regularPrice": 2499.99,
                "url": "https://www.bestbuy.com/site/6599123.p",
                "image": "https://pisces.bbystatic.com/image.jpg",
                "condition": "New",
                "manufacturer": "ASUS",
                "shortDescription": "Powerful gaming laptop.",
                "details": [
                    {"name": "System Memory (RAM)", "value": "32 gigabytes"},
                    {"name": "Total Storage Capacity", "value": "2 terabytes"},
                    {"name": "Screen Size", "value": "16 inches"},
                    {"name": "Refresh Rate", "value": "240Hz"},
                    {"name": "Display Type", "value": "OLED"},
                ],
            }
        ]
    }
    base = parse_bestbuy_products(products_payload)
    assert len(base) == 1
    assert base[0].raw_specs["ram_gb"] == 32
    assert base[0].raw_specs["ssd_gb"] == 2000
    assert base[0].raw_specs["panel_type"] == "OLED"

    open_box_payload = {
        "results": [
            {
                "sku": "6599123",
                "offers": [
                    {
                        "condition": "Excellent",
                        "prices": {"current": 1689.99, "regular": 2499.99},
                    }
                ],
            }
        ]
    }
    ob = parse_bestbuy_open_box(open_box_payload, {b.sku: b for b in base if b.sku})
    assert len(ob) == 1
    assert ob[0].price_usd == pytest.approx(1689.99)
    assert "open_box" in (ob[0].condition_hint or "")
    assert ob[0].raw_specs["ram_gb"] == 32
