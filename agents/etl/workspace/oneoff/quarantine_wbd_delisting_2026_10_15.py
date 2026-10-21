#!/usr/bin/env python3
"""
DATA_FIX (user-approved 2026-10-15): WBD delisting cleanup.

- Mark WBD inactive in gold.asset_registry (and silver mirror not tradeable).
- Quarantine the final yfinance bar 2026-10-05 (Open=0.0, Volume=40) as a
  delisting artifact: copy it to bronze.yf_suspect_bars and remove it from
  bronze.yf_prices, silver.unified_prices, gold.daily_ohlcv.

Idempotent. Run with /usr/bin/python3.
"""
import os, sys, json

ETL = os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl')
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

TICKER = 'WBD'
QDATE = '2026-10-05'
NOTE = ('DELISTED 2026-10-06: Paramount Skydance acquisition completed; '
        'last real trade 2026-10-02. Final yfinance 2026-10-05 bar '
        '(open=0, volume=40) quarantined as delisting artifact.')

def main():
    conn = get_connection()
    cur = conn.cursor()
    out = {'ticker': TICKER, 'quarantine_date': QDATE}

    cur.execute("SELECT is_active FROM gold.asset_registry WHERE ticker=%s", (TICKER,))
    out['gold_registry_before'] = cur.fetchone()
    cur.execute("SELECT is_active, is_tradeable FROM silver.asset_registry WHERE ticker=%s", (TICKER,))
    out['silver_registry_before'] = cur.fetchone()

    # Copy the artifact bar into quarantine (keep it visible as withheld).
    cur.execute("""
        INSERT INTO bronze.yf_suspect_bars
            (ticker, date, open, high, low, close, volume, adjusted_close,
             reason, detected_at, resolved_at)
        SELECT ticker, date, open, high, low, close, volume, adjusted_close,
               'delisting_artifact_open0_low_volume', NOW(), NULL
        FROM bronze.yf_prices
        WHERE ticker=%s AND date=%s
        ON CONFLICT (ticker, date) DO UPDATE SET
            reason = EXCLUDED.reason,
            detected_at = NOW(),
            resolved_at = NULL
    """, (TICKER, QDATE))
    out['quarantine_upserted'] = cur.rowcount

    for layer, table in [('bronze', 'bronze.yf_prices'),
                         ('silver', 'silver.unified_prices'),
                         ('gold', 'gold.daily_ohlcv')]:
        cur.execute(f"DELETE FROM {table} WHERE ticker=%s AND date=%s", (TICKER, QDATE))
        out[f'{layer}_deleted'] = cur.rowcount

    cur.execute("""
        UPDATE gold.asset_registry
        SET is_active = FALSE,
            description = CASE
                WHEN description IS NULL OR description = '' THEN %s
                WHEN description LIKE %s THEN description
                ELSE description || ' | ' || %s
            END,
            updated_at = NOW()
        WHERE ticker=%s
    """, (NOTE, '%DELISTED 2026-10-06%', NOTE, TICKER))
    out['gold_registry_updated'] = cur.rowcount

    cur.execute("""
        UPDATE silver.asset_registry
        SET is_active = FALSE,
            is_tradeable = FALSE,
            metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
                'delisted_date', '2026-10-06',
                'delisting_reason', 'Paramount Skydance acquisition completed',
                'quarantined_bar', '2026-10-05',
                'quarantine_reason', 'delisting_artifact_open0_low_volume'
            ),
            updated_at = NOW()
        WHERE ticker=%s
    """, (TICKER,))
    out['silver_registry_updated'] = cur.rowcount

    cur.execute("""
        INSERT INTO gold.audit_events (event_type, user_id, source, action, details)
        VALUES ('DATA_FIX', 'hermes', 'etl', 'wbd_delisting_quarantine', %s)
    """, (json.dumps({'ticker': TICKER, 'quarantine_date': QDATE,
                      'note': NOTE}),))
    out['audit_event_inserted'] = cur.rowcount

    conn.commit()

    # Verify post-state.
    cur.execute("SELECT is_active, description FROM gold.asset_registry WHERE ticker=%s", (TICKER,))
    out['gold_registry_after'] = cur.fetchone()
    cur.execute("SELECT is_active, is_tradeable FROM silver.asset_registry WHERE ticker=%s", (TICKER,))
    out['silver_registry_after'] = cur.fetchone()
    for layer, table in [('bronze', 'bronze.yf_prices'),
                         ('silver', 'silver.unified_prices'),
                         ('gold', 'gold.daily_ohlcv')]:
        cur.execute(f"SELECT count(*), max(date) FROM {table} WHERE ticker=%s", (TICKER,))
        out[f'{layer}_post'] = cur.fetchone()
    cur.execute("SELECT ticker, date, reason, resolved_at FROM bronze.yf_suspect_bars WHERE ticker=%s ORDER BY date", (TICKER,))
    out['suspect_rows'] = cur.fetchall()
    conn.close()
    print(json.dumps(out, indent=2, default=str))

if __name__ == '__main__':
    main()
