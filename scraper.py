"""
G2G Divine Orb Price Monitor
Logs the top listed sellers + prices (CAD) sorted by lowest price, online sellers only.
No login required. Appends results to prices.csv on every run.
"""

import asyncio
import csv
import json
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright, Response

# ── Config ────────────────────────────────────────────────────────────────────
TARGET_URL = (
    "https://www.g2g.com/categories/path-of-exile-2-currency/offer/group"
    "?fa=lgc_27013_platform%3Algc_27013_platform_62230"
    "%7Clgc_27013_tier%3Algc_27013_tier_54399"
    "&sort=lowest_price&include_offline=0"
)
CSV_FILE = "prices.csv"
MAX_ROWS = 10   # top 10 lowest-priced listings only
# URL already enforces: sort=lowest_price and include_offline=0 (online sellers only)
# ──────────────────────────────────────────────────────────────────────────────

FIELDNAMES = ["timestamp", "rank", "seller", "seller_level",
              "rating_pct", "units_sold", "price_cad"]


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_api_payload(raw: dict) -> list:
    candidates = [
        raw.get("payload", {}).get("results"),
        raw.get("payload", {}).get("offer_group"),
        raw.get("data", {}).get("results"),
        raw.get("results"),
        raw.get("offers"),
    ]
    for c in candidates:
        if isinstance(c, list) and c:
            return c
    return []


async def scrape_via_api(page) -> list:
    captured = []

    async def on_response(response: Response):
        url = response.url
        if "g2g.com" not in url:
            return
        if not any(k in url for k in ("offer", "listing", "group", "search")):
            return
        if response.status != 200:
            return
        try:
            body = await response.json()
        except Exception:
            return

        offers = parse_api_payload(body)
        if not offers:
            return

        log(f"  API hit → {url}  ({len(offers)} offers)")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

        for rank, offer in enumerate(offers[:MAX_ROWS], start=1):
            seller_obj   = offer.get("seller") or {}
            seller_name  = (seller_obj.get("display_name")
                            or offer.get("display_name")
                            or offer.get("username", "N/A"))
            seller_level = seller_obj.get("level", offer.get("seller_level", ""))
            rating       = (offer.get("positive_rate")
                            or offer.get("rating_percentage")
                            or seller_obj.get("positive_rate", ""))
            sold         = (offer.get("sold_count")
                            or offer.get("total_sold")
                            or offer.get("num_sold", ""))
            price        = (offer.get("converted_unit_price")
                            or offer.get("unit_price")
                            or offer.get("price")
                            or offer.get("display_price", "N/A"))

            captured.append({
                "timestamp":    timestamp,
                "rank":         rank,
                "seller":       seller_name,
                "seller_level": seller_level,
                "rating_pct":   rating,
                "units_sold":   sold,
                "price_cad":    price,
            })

    page.on("response", on_response)

    log("Navigating to listing page...")
    await page.goto(TARGET_URL, wait_until="networkidle", timeout=30_000)
    await page.wait_for_timeout(4_000)

    return captured


async def scrape_via_dom(page) -> list:
    log("Falling back to DOM scraping...")
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    rows = await page.evaluate("""() => {
        const results = [];
        const selectors = [
            '[data-cy="offer-item"]',
            '[class*="OfferItem"]',
            '[class*="offer-item"]',
            '[class*="offer_item"]',
            '.seller-card',
        ];

        let items = [];
        for (const sel of selectors) {
            items = [...document.querySelectorAll(sel)];
            if (items.length > 0) break;
        }

        items.slice(0, 20).forEach((item, i) => {
            const getText = (...sels) => {
                for (const s of sels) {
                    const el = item.querySelector(s);
                    if (el && el.innerText.trim()) return el.innerText.trim();
                }
                return '';
            };
            const seller = getText('[class*="seller"]', '[class*="username"]',
                                   '[data-cy*="seller"]', 'a[href*="/seller/"]');
            const price  = getText('[class*="price"]', '[class*="Price"]',
                                   '[data-cy*="price"]');
            results.push({ rank: i + 1, seller: seller || 'N/A', price: price || 'N/A' });
        });

        return results;
    }""")

    return [
        {
            "timestamp":    timestamp,
            "rank":         r["rank"],
            "seller":       r["seller"],
            "seller_level": "",
            "rating_pct":   "",
            "units_sold":   "",
            "price_cad":    r["price"],
        }
        for r in rows
    ]


def write_csv(records: list):
    path = Path(CSV_FILE)
    write_header = not path.exists()

    with open(path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
        writer.writerows(records)

    log(f"Wrote {len(records)} rows → {CSV_FILE}")


async def main():
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
            locale="en-CA",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = await context.new_page()

        try:
            records = await scrape_via_api(page)

            if not records:
                records = await scrape_via_dom(page)

            if not records:
                log("WARNING: No data captured. Writing failure marker.")
                records = [{
                    "timestamp":    timestamp,
                    "rank":         "",
                    "seller":       "SCRAPE_FAILED",
                    "seller_level": "",
                    "rating_pct":   "",
                    "units_sold":   "",
                    "price_cad":    "N/A",
                }]

        except Exception as e:
            log(f"ERROR: {e}")
            records = [{
                "timestamp":    timestamp,
                "rank":         "",
                "seller":       f"ERROR: {e}",
                "seller_level": "",
                "rating_pct":   "",
                "units_sold":   "",
                "price_cad":    "N/A",
            }]

        finally:
            await browser.close()

    write_csv(records)


if __name__ == "__main__":
    asyncio.run(main())
