#!/usr/bin/env python3
"""
funding_rate_fix.py
===================
Replaces volume-proxy funding_rate with actual Binance perpetual funding rate.

Goal: G10e_FUNDING_FIX
Agent: qr_etl
Priority: P1

What this does:
1. Fetches 8-hourly funding rates from Binance /fapi/v1/fundingRate
2. Aggregates to daily mean (3 obs/day at 00:00, 08:00, 16:00 UTC)
3. Computes rolling 364d z-score (same methodology as G6b)
4. Upserts into gold.crypto_funding_metrics

Symbols: BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT, DOGEUSDT,
         ADAUSDT, LINKUSDT, DOTUSDT, LTCUSDT, AVAXUSDT

History: from Binance futures launch (~2019-09) to present
"""
import os
import sys
import statistics
from collections import defaultdict
from datetime import datetime, timezone

import requests
import psycopg2

# ── Config ───────────────────────────────────────────────────────────────

SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "DOGEUSDT", "ADAUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT", "AVAXUSDT",
]

BINANCE_API = "https://fapi.binance.com/fapi/v1/fundingRate"
Z_WINDOW = 364
MIN_HISTORY = 30

DB_HOST = os.getenv("DB_HOST", "openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "aitrading")
DB_USER = os.getenv("DB_USER", "openclaw_user")
DB_PASSWORD = os.getenv("DB_PASSWORD", "NewStrongPasswordHere12")

# ── Helpers ──────────────────────────────────────────────────────────────

def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD,
    )


def fetch_funding_history(symbol: str) -> list[dict]:
    """Paginate through all funding rate history for a symbol."""
    all_data = []
    start_time = int(datetime(2019, 9, 1, tzinfo=timezone.utc).timestamp() * 1000)

    while True:
        params = {"symbol": symbol, "limit": 1000, "startTime": start_time}
        resp = requests.get(BINANCE_API, params=params, timeout=30)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_data.extend(batch)
        start_time = batch[-1]["fundingTime"] + 1
        if len(batch) < 1000:
            break

    return all_data


def aggregate_daily(records: list[dict]) -> dict[str, dict]:
    """Group 8h funding rates by date, compute daily mean and n_obs."""
    daily = defaultdict(list)
    for r in records:
        ts = datetime.fromtimestamp(r["fundingTime"] / 1000, tz=timezone.utc)
        daily[ts.strftime("%Y-%m-%d")].append(float(r["fundingRate"]))

    result = {}
    for date_str, rates in sorted(daily.items()):
        result[date_str] = {"mean": sum(rates) / len(rates), "n_obs": len(rates)}
    return result


def compute_z_scores(daily: dict[str, dict], symbol: str) -> list[tuple]:
    """Compute rolling z-scores and return upsert-ready tuples."""
    sorted_dates = sorted(daily.keys())
    rates = [daily[d]["mean"] for d in sorted_dates]
    rows = []

    for i, date_str in enumerate(sorted_dates):
        rate = rates[i]
        n_obs = daily[date_str]["n_obs"]

        if i < MIN_HISTORY:
            z = None
        else:
            start_idx = max(0, i - Z_WINDOW)
            window = rates[start_idx:i]
            if len(window) >= MIN_HISTORY:
                mu = statistics.mean(window)
                sigma = statistics.stdev(window) if len(window) > 1 else 0.0001
                z = (rate - mu) / sigma if sigma != 0 else 0.0
            else:
                z = None

        rows.append((
            symbol, date_str, rate,
            round(z, 4) if z is not None else None, n_obs,
        ))

    return rows


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("G10e_FUNDING_FIX — Binance Perpetual Funding Rate Ingest")
    print("=" * 60)

    all_rows = []

    for symbol in SYMBOLS:
        print(f"\nFetching {symbol} ...")
        records = fetch_funding_history(symbol)
        daily = aggregate_daily(records)
        rows = compute_z_scores(daily, symbol)
        all_rows.extend(rows)
        print(f"  {len(rows)} daily rows ({len(records)} 8h records)")

    print(f"\nTotal rows to upsert: {len(all_rows)}")

    conn = get_db_conn()
    cur = conn.cursor()

    upsert_sql = """
        INSERT INTO gold.crypto_funding_metrics
            (symbol, date, funding_rate_8h, funding_z, n_obs, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (symbol, date) DO UPDATE SET
            funding_rate_8h = EXCLUDED.funding_rate_8h,
            funding_z       = EXCLUDED.funding_z,
            n_obs           = EXCLUDED.n_obs,
            updated_at      = NOW()
    """

    batch_size = 1000
    for i in range(0, len(all_rows), batch_size):
        batch = all_rows[i : i + batch_size]
        cur.executemany(upsert_sql, batch)
        conn.commit()
        print(f"  Upserted batch {i // batch_size + 1}")

    cur.close()
    conn.close()

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
