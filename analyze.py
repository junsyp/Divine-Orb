"""
G2G Price Analyzer
Reads prices.csv and produces summary.csv with:
  - Daily average, high, and low price (CAD)
  - Number of readings per day
  - Weekly trend: % change in daily average vs. same day 7 days ago
"""

import csv
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PRICES_CSV  = "prices.csv"
SUMMARY_CSV = "summary.csv"

FIELDNAMES = [
    "date",
    "avg_price_cad",
    "low_price_cad",
    "high_price_cad",
    "num_readings",
    "weekly_trend_pct",   # % vs same day last week (blank if < 7 days of data)
]


def log(msg: str):
    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] {msg}", flush=True)


def to_float(val) -> float | None:
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def main():
    prices_path = Path(PRICES_CSV)
    if not prices_path.exists():
        log(f"{PRICES_CSV} not found — skipping analysis.")
        return

    # ── Aggregate prices by calendar date ────────────────────────────────────
    daily: dict[str, list[float]] = defaultdict(list)

    with open(prices_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # Skip failure/error sentinel rows
            seller = row.get("seller", "")
            if any(seller.startswith(s) for s in ("SCRAPE_FAILED", "ERROR")):
                continue

            price = to_float(row.get("price_cad"))
            ts    = row.get("timestamp", "")
            if price is None or not ts:
                continue

            date_str = ts[:10]  # "YYYY-MM-DD"
            daily[date_str].append(price)

    if not daily:
        log("No valid price data found in prices.csv — nothing to summarize.")
        return

    # ── Build per-day stats ───────────────────────────────────────────────────
    stats: dict[str, dict] = {}
    for date, prices in daily.items():
        stats[date] = {
            "date":          date,
            "avg_price_cad": round(sum(prices) / len(prices), 6),
            "low_price_cad": round(min(prices), 6),
            "high_price_cad": round(max(prices), 6),
            "num_readings":  len(prices),
        }

    # ── Weekly trend: % change vs same day 7 days prior ──────────────────────
    for date, row in stats.items():
        week_ago = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        if week_ago in stats:
            prev = stats[week_ago]["avg_price_cad"]
            curr = row["avg_price_cad"]
            row["weekly_trend_pct"] = round(((curr - prev) / prev) * 100, 2)
        else:
            row["weekly_trend_pct"] = ""   # not enough history yet

    # ── Write summary.csv (full rewrite each run) ─────────────────────────────
    with open(SUMMARY_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for date in sorted(stats):
            writer.writerow(stats[date])

    log(f"summary.csv written — {len(stats)} day(s) of data.")

    # ── Print latest snapshot to Actions log ─────────────────────────────────
    latest_date = max(stats)
    r = stats[latest_date]
    trend = f"{r['weekly_trend_pct']:+.2f}%" if r["weekly_trend_pct"] != "" else "n/a (< 7 days data)"
    log(f"  Latest day  : {latest_date}")
    log(f"  Avg price   : {r['avg_price_cad']} CAD")
    log(f"  Low / High  : {r['low_price_cad']} / {r['high_price_cad']} CAD")
    log(f"  Weekly trend: {trend}")


if __name__ == "__main__":
    main()
