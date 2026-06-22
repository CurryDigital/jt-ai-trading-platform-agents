# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Bronze Ingestion: Coinbase Advanced Trade API
Tables:
  bronze.coinbase_crypto_ohlcv — OHLCV candles for crypto pairs
Source: Coinbase Advanced Trade REST API (public)
Env:   COINBASE_API_KEY, COINBASE_API_SECRET (optional, for private endpoints)
"""
import sys, os, json
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import datetime, timezone, timedelta

try:
    import requests
except ImportError:
    print("⚠️  requests not installed — run: pip install requests")
    sys.exit(1)

BASE_URL = 'https://api.coinbase.com/api/v3/brokerage'

DEFAULT_PRODUCTS  = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BNB-USD', 'XRP-USD']
GRANULARITY_MAP = {
    '1d': 'ONE_DAY',
    '6h': 'SIX_HOUR',
    '1h': 'ONE_HOUR',
}

def cb_get(path: str, params: dict = None) -> dict:
    r = requests.get(f"{BASE_URL}/{path.lstrip('/')}", params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def get_active_products(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE asset_class = 'CRYPTO' AND is_active = TRUE
    """)
    rows = [r[0].replace('USDT', '-USD').replace('USDC', '-USD') for r in cur.fetchall()]
    return rows if rows else DEFAULT_PRODUCTS


def ingest_ohlcv(products: list = None, granularity: str = '1d', days_back: int = 14):
    conn = get_connection()
    if products is None:
        products = get_active_products(conn)

    cur      = conn.cursor()
    inserted = 0
    gran     = GRANULARITY_MAP.get(granularity, 'ONE_DAY')
    start_dt = datetime.now(timezone.utc) - timedelta(days=days_back)

    for product_id in products:
        try:
            data = cb_get(f'products/{product_id}/candles', {
                'start':       str(int(start_dt.timestamp())),
                'end':         str(int(datetime.now(timezone.utc).timestamp())),
                'granularity': gran,
            })
            candles = data.get('candles', [])
            for c in candles:
                ts = datetime.fromtimestamp(int(c['start']), tz=timezone.utc)
                # Coinbase ticker = product_id stripped of '-USD' suffix
                ticker = product_id.replace('-USD', 'USDT')
                try:
                    cur.execute("""
                        INSERT INTO bronze.coinbase_crypto_ohlcv
                            (ticker, interval, timestamp,
                             open, high, low, close, volume,
                             raw_data, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, interval, timestamp) DO UPDATE SET
                            close  = EXCLUDED.close,
                            volume = EXCLUDED.volume
                    """, (
                        ticker, granularity, ts,
                        c.get('open'), c.get('high'),
                        c.get('low'),  c.get('close'),
                        c.get('volume'),
                        json.dumps(c),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {product_id}: {e}")
        except Exception as e:
            print(f"  Product error {product_id}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.coinbase_crypto_ohlcv — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_ohlcv()
