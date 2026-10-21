#!/usr/bin/env python3
"""
Bronze FX: dated USD->HKD reference rates -> gold.fx_rates (t_65d96f4a).

Source: frankfurter.dev (ECB daily reference rates, business days only).
This is one of TWO sanctioned writers of gold.fx_rates (see shared/scripts/fx.py):
  1. bronze/ibkr/ingest_ibkr_tws.py — IBKR ExchangeRate account payload (when
     the gateway delivers those rows; source='ibkr_account_summary')
  2. THIS script — dated ECB rates (source='frankfurter_ecb'), the reliable
     business-day refresh so the shared conversion layer never goes stale.

Rates carry an explicit as_of_date. On conflict the fresher fetch wins; IBKR
captures the same date simply overwrite with their own source label.
Idempotent; safe to run daily.
"""
import json
import os
import sys
import urllib.request
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection

LOOKBACK_DAYS = int(os.environ.get('FX_SEED_LOOKBACK_DAYS', '45'))
PAIRS = (('USD', 'HKD'),)


def fetch_series(base, quote, start, end):
    url = f'https://api.frankfurter.dev/v1/{start}..{end}?base={base}&symbols={quote}'
    req = urllib.request.Request(url, headers={'User-Agent': 'trading-platform-fx-ingest/1.0'})
    with urllib.request.urlopen(req, timeout=20) as r:
        payload = json.loads(r.read().decode())
    return {d: float(v[quote]) for d, v in payload.get('rates', {}).items() if v.get(quote)}


def run():
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    conn = get_connection()
    cur = conn.cursor()
    total = 0
    for base, quote in PAIRS:
        try:
            series = fetch_series(base, quote, start, end)
        except Exception as e:
            # Honest fail: stale rates trip the fx layer's staleness ALERT;
            # do NOT write fabricated or undated rows.
            print(f"ALERT FX_INGEST_FETCH_FAILED: {base}/{quote}: {e}", flush=True)
            conn.close()
            raise SystemExit(2)
        if not series:
            print(f"ALERT FX_INGEST_EMPTY: no {base}/{quote} rows from frankfurter", flush=True)
            conn.close()
            raise SystemExit(2)
        for d, rate in sorted(series.items()):
            cur.execute("""
                INSERT INTO gold.fx_rates (from_ccy, to_ccy, rate, as_of_date, source)
                VALUES (%s, %s, %s, %s, 'frankfurter_ecb')
                ON CONFLICT (from_ccy, to_ccy, as_of_date) DO UPDATE SET
                    rate = EXCLUDED.rate, source = EXCLUDED.source, fetched_at = NOW()
            """, (base, quote, rate, d))
            total += 1
        latest = max(series)
        print(f"✅ gold.fx_rates {base}->{quote}: {len(series)} dated rows upserted "
              f"(latest {latest} @ {series[latest]})")
    conn.commit()
    conn.close()
    print(f"done — {total} rows")


if __name__ == '__main__':
    run()
