#!/usr/bin/env python3
"""
Bronze Ingestion: Binance
Tables:
  bronze.binance_crypto_ohlcv    — OHLCV bars (1d, 4h, 1h intervals)
  bronze.binance_funding_rates   — perpetual futures funding rates
Source: Binance REST API (public endpoints — no API key required for public data)
Env:   BINANCE_API_KEY, BINANCE_API_SECRET (optional — for higher rate limits)
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

BASE_URL = 'https://api.binance.com'
HEADERS  = {}
API_KEY  = os.environ.get('BINANCE_API_KEY', '')
if API_KEY:
    HEADERS['X-MBX-APIKEY'] = API_KEY

DEFAULT_SYMBOLS   = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT']
DEFAULT_INTERVALS = ['1d', '4h']

def binance_get(path: str, params: dict = None) -> list:
    r = requests.get(f"{BASE_URL}{path}", params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json()

def get_active_crypto_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE asset_class = 'CRYPTO' AND is_active = TRUE
    """)
    rows = [r[0] for r in cur.fetchall()]
    return rows if rows else DEFAULT_SYMBOLS

# ── OHLCV ─────────────────────────────────────────────────────────────────────

def ingest_ohlcv(symbols: list = None, intervals: list = None, days_back: int = 14):
    conn = get_connection()
    if symbols   is None: symbols   = get_active_crypto_tickers(conn)
    if intervals is None: intervals = DEFAULT_INTERVALS
    cur      = conn.cursor()
    inserted = 0
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp() * 1000)

    for symbol in symbols:
        for interval in intervals:
            try:
                klines = binance_get('/api/v3/klines', {
                    'symbol':    symbol,
                    'interval':  interval,
                    'startTime': start_ms,
                    'limit':     1000,
                })
                for k in klines:
                    ts = datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc)
                    try:
                        cur.execute("""
                            INSERT INTO bronze.binance_crypto_ohlcv
                                (ticker, interval, timestamp,
                                 open, high, low, close, volume,
                                 quote_volume, trades_count,
                                 taker_buy_volume, taker_buy_quote_volume,
                                 ingested_at)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                            ON CONFLICT (ticker, interval, timestamp) DO UPDATE SET
                                close        = EXCLUDED.close,
                                volume       = EXCLUDED.volume
                        """, (
                            symbol, interval, ts,
                            k[1], k[2], k[3], k[4], k[5],
                            k[7], k[8], k[9], k[10],
                        ))
                        inserted += 1
                    except Exception as e:
                        print(f"    Row error {symbol}/{interval} {ts}: {e}")
            except Exception as e:
                print(f"  Symbol error {symbol}/{interval}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.binance_crypto_ohlcv — {inserted} rows upserted")


# ── Funding Rates ─────────────────────────────────────────────────────────────

def ingest_funding_rates(symbols: list = None, days_back: int = 30):
    conn = get_connection()
    if symbols is None:
        symbols = [s for s in get_active_crypto_tickers(conn) if not s.endswith('SPOT')]
    cur      = conn.cursor()
    inserted = 0
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=days_back)).timestamp() * 1000)

    for symbol in symbols:
        try:
            rows = binance_get('/fapi/v1/fundingRate', {
                'symbol':    symbol,
                'startTime': start_ms,
                'limit':     1000,
            })
            for row in rows:
                ts = datetime.fromtimestamp(row['fundingTime'] / 1000, tz=timezone.utc)
                try:
                    cur.execute("""
                        INSERT INTO bronze.binance_funding_rates
                            (ticker, funding_time, funding_rate, mark_price,
                             raw_data, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, funding_time) DO UPDATE SET
                            funding_rate = EXCLUDED.funding_rate
                    """, (
                        symbol, ts,
                        row.get('fundingRate'),
                        row.get('markPrice'),
                        json.dumps(row),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {symbol}: {e}")
        except Exception as e:
            # Futures endpoint may 400 for spot-only symbols
            if 'Invalid symbol' not in str(e):
                print(f"  Funding rate error {symbol}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.binance_funding_rates — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_ohlcv()
    ingest_funding_rates()
