#!/usr/bin/env python3
"""Fetch live IBKR positions + account summary via TWS API (ib_insync)."""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import asyncio

# ib_insync/eventkit eagerly grabs the event loop at import time.
# Python 3.14+ disallows get_event_loop() in non-main threads / before a loop exists.
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from ib_insync import IB, util
from db import get_connection
from datetime import datetime

IBKR_HOST = os.environ.get('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.environ.get('IBKR_PORT', 14002))
IBKR_CLIENT_ID = int(os.environ.get('IBKR_CLIENT_ID', 99))

async def fetch_positions_and_summary():
    ib = IB()
    try:
        await ib.connectAsync(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=10)
        print(f"Connected to {IBKR_HOST}:{IBKR_PORT}")
    except Exception as e:
        print(f"⚠️  IBKR connection failed: {e}")
        return [], {}

    account = ib.wrapper.accounts[0] if ib.wrapper.accounts else ''
    
    # Get positions
    positions = ib.positions(account) if account else ib.positions()
    portfolio = ib.portfolio(account) if account else ib.portfolio()
    
    # Build lookup from portfolio for market values
    portfolio_lookup = {}
    for p in portfolio:
        portfolio_lookup[p.contract.conId] = {
            'market_price': p.marketPrice,
            'market_value': p.marketValue,
            'unrealized_pnl': p.unrealizedPNL,
            'realized_pnl': p.realizedPNL,
        }
    
    result = []
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
            await asyncio.sleep(2)
            market_price = ticker_obj.last or ticker_obj.close or ticker_obj.marketPrice() or pos.avgCost
            market_value = pos.position * market_price if market_price else 0
            unrealized_pnl = market_value - (pos.position * pos.avgCost) if pos.avgCost else 0
            ib.cancelMktData(contract)
        
        unrealized_pnl_pct = (unrealized_pnl / (pos.position * pos.avgCost) * 100) if pos.position and pos.avgCost else 0
        
        result.append({
            'account': account,
            'ticker': contract.symbol,
            'conid': conid,
            'asset_class': contract.secType,
            'quantity': pos.position,
            'avg_cost': pos.avgCost,
            'market_price': market_price,
            'market_value': market_value,
            'unrealized_pnl': unrealized_pnl,
            'unrealized_pnl_pct': unrealized_pnl_pct,
            'currency': contract.currency,
            'exchange': contract.exchange,
        })
    
    # Get account summary
    summary = {}
    if account:
        for av in ib.accountValues(account=account):
            if av.tag in ('CashBalance', 'NetLiquidation', 'AvailableFunds', 'BuyingPower', 'EquityWithLoanValue'):
                key = f"{av.tag}_{av.currency}" if av.currency else av.tag
                summary[key] = av.value
    
    ib.disconnect()
    return result, summary

def write_positions(rows):
    conn = get_connection()
    cur = conn.cursor()
    if not rows:
        print("No positions to write — clearing stale positions")
        cur.execute("TRUNCATE bronze.ibkr_positions_live;")
        conn.commit()
        conn.close()
        return
    inserted = 0
    for r in rows:
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
                r['account'], r['ticker'], r['conid'], r['asset_class'],
                r['quantity'], r['avg_cost'], r['market_price'], r['market_value'],
                r['unrealized_pnl'], r['unrealized_pnl_pct'],
                r['currency'], r['exchange'],
            ))
            inserted += 1
        except Exception as e:
            print(f"    Write error {r['ticker']}: {e}")
    conn.commit()
    conn.close()
    print(f"✅ bronze.ibkr_positions_live — {inserted} rows upserted")

def write_account_summary(summary, positions_count):
    if not summary:
        return
    conn = get_connection()
    cur = conn.cursor()
    try:
        net_liq = summary.get('NetLiquidation_HKD') or summary.get('NetLiquidation_BASE') or 0
        cash_hkd = summary.get('CashBalance_HKD', 0)
        cash_usd = summary.get('CashBalance_USD', 0)
        available = summary.get('AvailableFunds_HKD', 0)
        buying_power = summary.get('BuyingPower_HKD', 0)
        
        cur.execute("""
            INSERT INTO bronze.ibkr_account_summary
                (account, net_liquidation, cash_hkd, cash_usd, available_funds, buying_power, position_count, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (account) DO UPDATE SET
                net_liquidation = EXCLUDED.net_liquidation,
                cash_hkd = EXCLUDED.cash_hkd,
                cash_usd = EXCLUDED.cash_usd,
                available_funds = EXCLUDED.available_funds,
                buying_power = EXCLUDED.buying_power,
                position_count = EXCLUDED.position_count,
                fetched_at = NOW()
        """, (summary.get('account', ''), net_liq, cash_hkd, cash_usd, available, buying_power, positions_count))
        conn.commit()
        print(f"✅ bronze.ibkr_account_summary — {summary}")
    except Exception as e:
        print(f"⚠️  Account summary write failed: {e}")
    finally:
        conn.close()

async def main():
    rows, summary = await fetch_positions_and_summary()
    for r in rows:
        print(f"  {r['ticker']:8} {r['quantity']:>10.2f} @ {r['avg_cost']:<10.2f} mv={r['market_value']:>12.2f}")
    if summary:
        print(f"  Account summary: {summary}")
    write_positions(rows)
    write_account_summary(summary, len(rows))

if __name__ == "__main__":
    asyncio.run(main())
