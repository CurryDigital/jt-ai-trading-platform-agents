#!/usr/bin/env python3
"""
Bronze Ingestion: Interactive Brokers (IBKR) via TWS API (ib_insync)
Tables:
  bronze.ibkr_fx_bars        — historical FX OHLC bars from IBKR
  bronze.ibkr_fx_ticks       — raw bid/ask tick stream
  bronze.ibkr_positions_live — live account positions snapshot
Source: IBKR TWS API (binary socket on port 4002)
Env:   IBKR_GATEWAY_HOST  (default: 52.74.14.181)
       IBKR_GATEWAY_PORT  (default: 4002)
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import asyncio

# ib_insync/eventkit eagerly grabs the event loop at import time.
# Python 3.14+ disallows get_event_loop() in non-main threads / before a loop exists.
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from ib_insync import IB, Forex
from db import get_connection
from datetime import datetime, timezone

IBKR_HOST = os.environ.get('IBKR_GATEWAY_HOST', '127.0.0.1')
IBKR_PORT = int(os.environ.get('IBKR_GATEWAY_PORT', 14002))
IBKR_CLIENT_ID = int(os.environ.get('IBKR_CLIENT_ID', 98))

FX_PAIRS = ['EURUSD', 'USDJPY', 'GBPUSD', 'USDCHF', 'AUDUSD', 'USDCAD', 'NZDUSD']


def get_ib():
    """Connect to IBKR TWS/Gateway and return IB instance."""
    ib = IB()
    try:
        ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=10)
        print(f"Connected to IBKR TWS API at {IBKR_HOST}:{IBKR_PORT}")
        return ib
    except Exception as e:
        print(f"⚠️  IBKR connection failed: {e}")
        return None


# ── Live Positions ────────────────────────────────────────────────────────────

def ingest_positions_live():
    ib = get_ib()
    if not ib:
        print("⚠️  No IBKR connection — skipping ibkr_positions_live")
        return

    account = ib.wrapper.accounts[0] if ib.wrapper.accounts else ''
    positions = ib.positions(account) if account else ib.positions()
    portfolio = ib.portfolio(account) if account else ib.portfolio()

    portfolio_lookup = {}
    for p in portfolio:
        portfolio_lookup[p.contract.conId] = {
            'market_price': p.marketPrice,
            'market_value': p.marketValue,
            'unrealized_pnl': p.unrealizedPNL,
            'realized_pnl': p.realizedPNL,
        }

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    for pos in positions:
        contract = pos.contract
        conid = contract.conId

        if conid in portfolio_lookup:
            pl = portfolio_lookup[conid]
            market_price = pl['market_price'] or pos.avgCost
            market_value = pl['market_value'] or (pos.position * market_price)
            unrealized_pnl = pl['unrealized_pnl'] or 0
        else:
            ticker_obj = ib.reqMktData(contract, '', False, False)
            ib.sleep(1)
            market_price = ticker_obj.last or ticker_obj.close or ticker_obj.marketPrice() or pos.avgCost
            market_value = pos.position * market_price if market_price else 0
            unrealized_pnl = market_value - (pos.position * pos.avgCost) if pos.avgCost else 0
            ib.cancelMktData(contract)

        unrealized_pnl_pct = (unrealized_pnl / (pos.position * pos.avgCost) * 100) if pos.position and pos.avgCost else 0

        try:
            cur.execute("""
                INSERT INTO bronze.ibkr_positions_live
                    (account, ticker, conid, asset_class,
                     quantity, avg_cost, market_price, market_value,
                     unrealized_pnl, unrealized_pnl_pct,
                     currency, exchange, fetched_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (account, ticker) DO UPDATE SET
                    quantity       = EXCLUDED.quantity,
                    avg_cost       = EXCLUDED.avg_cost,
                    market_price   = EXCLUDED.market_price,
                    market_value   = EXCLUDED.market_value,
                    unrealized_pnl = EXCLUDED.unrealized_pnl,
                    unrealized_pnl_pct = EXCLUDED.unrealized_pnl_pct,
                    fetched_at     = NOW()
            """, (
                account, contract.symbol, conid, contract.secType,
                pos.position, pos.avgCost, market_price, market_value,
                unrealized_pnl, unrealized_pnl_pct,
                contract.currency, contract.exchange,
            ))
            inserted += 1
        except Exception as e:
            print(f"    Position error {contract.symbol}: {e}")

    conn.commit()
    conn.close()
    ib.disconnect()
    print(f"✅ bronze.ibkr_positions_live — {inserted} rows upserted")


# ── FX Bars ───────────────────────────────────────────────────────────────────

def ingest_fx_bars(bar_size: str = '1 day', duration: str = '5 D'):
    """
    Fetch OHLC bars for FX pairs via IBKR reqHistoricalData.
    bar_size: '1 day', '1 hour', '5 mins'
    duration: '5 D', '1 M', '1 Y'
    """
    ib = get_ib()
    if not ib:
        print("⚠️  No IBKR connection — skipping ibkr_fx_bars")
        return

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    for pair in FX_PAIRS:
        try:
            contract = Forex(pair)
            bars = ib.reqHistoricalData(
                contract,
                endDateTime='',
                durationStr=duration,
                barSizeSetting=bar_size,
                whatToShow='MIDPOINT',
                useRTH=False,
                formatDate=1
            )
            for bar in bars:
                try:
                    if isinstance(bar.date, datetime):
                        ts = bar.date.replace(tzinfo=timezone.utc)
                    else:
                        # bar.date can be string 'YYYYMMDD' or 'YYYY-MM-DD'
                        date_str = str(bar.date)
                        if '-' in date_str:
                            ts = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                        else:
                            ts = datetime.strptime(date_str, '%Y%m%d').replace(tzinfo=timezone.utc)
                    cur.execute("""
                        INSERT INTO bronze.ibkr_fx_bars
                            (pair, bar_size, timestamp,
                             open_bid, high_bid, low_bid, close_bid,
                             volume, ingested_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (pair, bar_size, timestamp) DO UPDATE SET
                            close_bid = EXCLUDED.close_bid,
                            volume = EXCLUDED.volume
                    """, (
                        pair, bar_size, ts,
                        bar.open, bar.high, bar.low, bar.close,
                        bar.volume,
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Bar error {pair}: {e}")
        except Exception as e:
            print(f"  FX bars error {pair}: {e}")

    conn.commit()
    conn.close()
    ib.disconnect()
    print(f"✅ bronze.ibkr_fx_bars — {inserted} rows upserted")


# ── FX Ticks (latest snapshot) ────────────────────────────────────────────────

def ingest_fx_ticks():
    """Snapshot current bid/ask for FX pairs from live market data."""
    ib = get_ib()
    if not ib:
        print("⚠️  No IBKR connection — skipping ibkr_fx_ticks")
        return

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    for pair in FX_PAIRS:
        try:
            contract = Forex(pair)
            ticker = ib.reqMktData(contract, '', False, False)
            ib.sleep(2)
            bid = ticker.bid
            ask = ticker.ask
            ib.cancelMktData(contract)

            if bid is not None or ask is not None:
                cur.execute("""
                    INSERT INTO bronze.ibkr_fx_ticks
                        (pair, timestamp, bid, ask, ingested_at)
                    VALUES (%s, NOW(), %s, %s, NOW())
                """, (pair, bid, ask))
                inserted += 1
        except Exception as e:
            print(f"  FX tick error {pair}: {e}")

    conn.commit()
    conn.close()
    ib.disconnect()
    print(f"✅ bronze.ibkr_fx_ticks — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_positions_live()
    # ingest_fx_bars()  # Disabled: paper account lacks FX historical data subscription
    ingest_fx_ticks()
