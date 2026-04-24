#!/usr/bin/env python3
"""
Bronze Ingestion: Interactive Brokers (IBKR)
Tables:
  bronze.ibkr_fx_bars        — historical FX OHLC bars from IBKR
  bronze.ibkr_fx_ticks       — raw bid/ask tick stream
  bronze.ibkr_positions_live — live account positions snapshot
Source: IBKR Client Portal Gateway (REST API on localhost:5000)
Env:   IBKR_GATEWAY_URL  (default: https://localhost:5000)
       IBKR_ACCOUNT      (default: reads from API)
"""
import sys, os, json
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import datetime, timezone

try:
    import requests
    requests.packages.urllib3.disable_warnings()  # self-signed cert
except ImportError:
    print("⚠️  requests not installed — run: pip install requests")
    sys.exit(1)

GATEWAY  = os.environ.get('IBKR_GATEWAY_URL', 'https://localhost:5000/v1/api')
ACCOUNT  = os.environ.get('IBKR_ACCOUNT', '')

def gw_get(path: str, params: dict = None):
    """GET from IBKR Client Portal Gateway."""
    url = f"{GATEWAY}/{path.lstrip('/')}"
    r   = requests.get(url, params=params, verify=False, timeout=15)
    r.raise_for_status()
    return r.json()

def get_account_id() -> str:
    global ACCOUNT
    if ACCOUNT:
        return ACCOUNT
    try:
        accts = gw_get('portfolio/accounts')
        ACCOUNT = accts[0]['id']
        return ACCOUNT
    except Exception as e:
        print(f"⚠️  Could not get account ID: {e}")
        return ''

# ── Live Positions ────────────────────────────────────────────────────────────

def ingest_positions_live():
    conn = get_connection()
    cur  = conn.cursor()
    acct = get_account_id()
    if not acct:
        print("⚠️  No IBKR account — skipping ibkr_positions_live")
        conn.close()
        return

    inserted = 0
    try:
        positions = gw_get(f'portfolio/{acct}/positions/0')
        for pos in positions:
            try:
                ticker = pos.get('ticker') or pos.get('symbol') or pos.get('conid', '')
                cur.execute("""
                    INSERT INTO bronze.ibkr_positions_live
                        (account, ticker, conid, asset_class,
                         quantity, avg_cost, market_price, market_value,
                         unrealized_pnl, unrealized_pnl_pct,
                         currency, exchange, fetched_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (account, ticker) DO UPDATE SET
                        quantity       = EXCLUDED.quantity,
                        market_price   = EXCLUDED.market_price,
                        market_value   = EXCLUDED.market_value,
                        unrealized_pnl = EXCLUDED.unrealized_pnl,
                        fetched_at     = NOW()
                """, (
                    acct,
                    str(ticker),
                    pos.get('conid'),
                    pos.get('assetClass'),
                    pos.get('position'),
                    pos.get('avgCost'),
                    pos.get('mktPrice'),
                    pos.get('mktValue'),
                    pos.get('unrealizedPnl'),
                    pos.get('unrealizedPnlPercent'),
                    pos.get('currency'),
                    pos.get('listingExchange'),
                ))
                inserted += 1
            except Exception as e:
                print(f"    Position error: {e}")
    except Exception as e:
        print(f"  IBKR positions error: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.ibkr_positions_live — {inserted} rows upserted")


# ── FX Bars ───────────────────────────────────────────────────────────────────

FX_PAIRS = ['EURUSD', 'USDJPY', 'GBPUSD', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD']

def ingest_fx_bars(bar_size: str = '1 day', period: str = '5 D'):
    """
    Fetch OHLC bars for FX pairs via IBKR market data history.
    bar_size: '1 day', '1 hour', '5 mins'
    period:   '5 D', '1 M', '1 Y'
    """
    conn = get_connection()
    cur  = conn.cursor()
    inserted = 0

    for pair in FX_PAIRS:
        try:
            # IBKR uses conid for FX pairs — simplified approach via /iserver/marketdata/history
            # In production, resolve conid first with /iserver/secdef/search
            data = gw_get('iserver/marketdata/history', {
                'conid': pair,   # placeholder — replace with real conid
                'period': period,
                'bar': bar_size,
            })
            bars = data.get('data', [])
            for bar in bars:
                ts = datetime.fromtimestamp(bar.get('t', 0) / 1000, tz=timezone.utc)
                try:
                    cur.execute("""
                        INSERT INTO bronze.ibkr_fx_bars
                            (pair, bar_size, timestamp,
                             open_bid, high_bid, low_bid, close_bid,
                             volume, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (pair, bar_size, timestamp) DO UPDATE SET
                            close_bid = EXCLUDED.close_bid
                    """, (
                        pair, bar_size, ts,
                        bar.get('o'), bar.get('h'), bar.get('l'), bar.get('c'),
                        bar.get('v'),
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Bar error {pair}: {e}")
        except Exception as e:
            print(f"  FX bars error {pair}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.ibkr_fx_bars — {inserted} rows upserted")


# ── FX Ticks (latest snapshot) ────────────────────────────────────────────────

def ingest_fx_ticks():
    """Snapshot current bid/ask for FX pairs from live market data."""
    conn = get_connection()
    cur  = conn.cursor()
    inserted = 0

    for pair in FX_PAIRS:
        try:
            data = gw_get('iserver/marketdata/snapshot', {
                'conids': pair,
                'fields': '31,84,86',  # 31=last, 84=bid, 86=ask
            })
            for item in data:
                try:
                    cur.execute("""
                        INSERT INTO bronze.ibkr_fx_ticks
                            (pair, timestamp, bid, ask, ingested_at)
                        VALUES (%s, NOW(), %s, %s, NOW())
                    """, (
                        pair,
                        item.get('84'),  # bid
                        item.get('86'),  # ask
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Tick error {pair}: {e}")
        except Exception as e:
            print(f"  FX tick error {pair}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.ibkr_fx_ticks — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_positions_live()
    ingest_fx_bars()
    ingest_fx_ticks()
