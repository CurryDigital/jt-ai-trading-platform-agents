# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Bronze → Silver: Binance Funding Rates
======================================
Fetches 8-hour funding rates from Binance futures, aggregates to daily mean,
and computes a 30-day rolling z-score.

Source:  Binance REST  /fapi/v1/fundingRate  (public endpoint)
Output:  silver.funding_rates_daily

Columns
-------
date               UTC calendar date
symbol             trading pair (e.g. BTCUSDT)
funding_rate_8h    mean of all 8h intervals in that UTC day
funding_z          rolling 30-day z-score of funding_rate_8h
n_obs              count of 8h observations contributing to the mean
calculated_at      ingestion timestamp

Usage
-----
python bronze/binance/ingest_funding_rates.py [days_back]
"""
import sys, os, json, math
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    print("requests not installed — run: pip install requests")
    sys.exit(1)

BASE_URL = 'https://fapi.binance.com'
HEADERS  = {}
API_KEY  = os.environ.get('BINANCE_API_KEY', '')
if API_KEY:
    HEADERS['X-MBX-APIKEY'] = API_KEY

DEFAULT_SYMBOLS = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
    'ADAUSDT', 'DOGEUSDT', 'LINKUSDT', 'DOTUSDT', 'LTCUSDT',
    'AVAXUSDT', 'UNIUSDT', 'ATOMUSDT', 'ETCUSDT', 'FILUSDT',
    'ALGOUSDT', 'NEARUSDT', 'APTUSDT', 'ARBUSDT',
]


def binance_get(path: str, params: dict = None) -> list:
    """GET from Binance futures API; return JSON list."""
    r = requests.get(f"{BASE_URL}{path}", params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and 'code' in data:
        raise RuntimeError(f"Binance API error {data['code']}: {data.get('msg')}")
    return data


def get_active_symbols(conn) -> list:
    """Pull active CRYPTO tickers from gold.asset_registry; fall back to defaults."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE asset_class = 'CRYPTO' AND is_active = TRUE
    """)
    rows = [r[0] for r in cur.fetchall()]
    # Strip any SPOT suffix and ensure USDT-pair format
    cleaned = []
    for s in rows:
        s = s.replace('SPOT', '').replace('-USD', '').strip()
        if s and not s.endswith('USDT'):
            s = s + 'USDT'
        cleaned.append(s)
    return cleaned if cleaned else DEFAULT_SYMBOLS


def fetch_funding_rates(symbol: str, start_ms: int, end_ms: int) -> list:
    """Paginated fetch of funding-rate history for one symbol."""
    all_rows = []
    params = {
        'symbol':    symbol,
        'startTime': start_ms,
        'endTime':   end_ms,
        'limit':     1000,
    }
    while True:
        batch = binance_get('/fapi/v1/fundingRate', params)
        if not batch:
            break
        all_rows.extend(batch)
        if len(batch) < 1000:
            break
        # advance startTime past last record
        params['startTime'] = batch[-1]['fundingTime'] + 1
    return all_rows


def validate_row(row: dict) -> None:
    """Raise on malformed funding-rate records."""
    if not isinstance(row, dict):
        raise ValueError("Funding rate row is not a dict")
    if 'fundingRate' not in row or 'fundingTime' not in row:
        raise ValueError(f"Missing keys in funding rate row: {row.keys()}")
    rate = row['fundingRate']
    if rate is None or math.isnan(float(rate)) or math.isinf(float(rate)):
        raise ValueError(f"Invalid fundingRate value: {rate}")


def ingest(days_back: int = 90):
    conn = get_connection()
    symbols = get_active_symbols(conn)
    cur = conn.cursor()

    end_dt   = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    start_dt = end_dt - timedelta(days=days_back)
    start_ms = int(start_dt.timestamp() * 1000)
    end_ms   = int((end_dt + timedelta(days=1)).timestamp() * 1000)  # inclusive buffer

    inserted = 0
    failed   = []

    for symbol in symbols:
        try:
            rows = fetch_funding_rates(symbol, start_ms, end_ms)
            if not rows:
                continue

            # Aggregate to daily mean
            daily = {}
            for r in rows:
                validate_row(r)
                ts = datetime.fromtimestamp(r['fundingTime'] / 1000, tz=timezone.utc)
                d  = ts.date()
                daily.setdefault(d, []).append(float(r['fundingRate']))

            if not daily:
                continue

            # Sort dates so rolling z-score is chronological
            sorted_dates = sorted(daily.keys())

            # Compute 30-day rolling z-score manually (needs ordered list)
            window = 30
            values = [sum(daily[d]) / len(daily[d]) for d in sorted_dates]
            z_scores = []
            for i, val in enumerate(values):
                lo = max(0, i - window + 1)
                slice_vals = values[lo:i + 1]
                if len(slice_vals) < 2:
                    z_scores.append(None)
                    continue
                mu = sum(slice_vals) / len(slice_vals)
                sigma = math.sqrt(sum((x - mu) ** 2 for x in slice_vals) / len(slice_vals))
                z_scores.append((val - mu) / sigma if sigma > 0 else 0.0)

            for d, val, z in zip(sorted_dates, values, z_scores):
                cur.execute("""
                    INSERT INTO silver.funding_rates_daily
                        (symbol, date, funding_rate_8h, funding_z, n_obs, calculated_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (symbol, date) DO UPDATE SET
                        funding_rate_8h = EXCLUDED.funding_rate_8h,
                        funding_z       = EXCLUDED.funding_z,
                        n_obs           = EXCLUDED.n_obs,
                        calculated_at   = NOW()
                """, (
                    symbol, d, round(val, 12),
                    round(z, 6) if z is not None else None,
                    len(daily[d]),
                ))
                inserted += 1

        except Exception as e:
            failed.append((symbol, str(e)))
            # Non-fatal per-symbol; continue with next symbol

    conn.commit()
    conn.close()

    print(f"✅ silver.funding_rates_daily — {inserted} rows upserted")
    if failed:
        print(f"⚠️  {len(failed)} symbols failed:")
        for sym, err in failed[:5]:
            print(f"    {sym}: {err}")


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 90
    ingest(days_back=days)
