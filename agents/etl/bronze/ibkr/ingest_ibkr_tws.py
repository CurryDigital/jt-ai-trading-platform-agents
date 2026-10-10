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
# Account base currency (DUP825942 = HKD). Ops-controlled config, NOT an FX
# rate — used only to label rows and select the BASE aggregate.
IBKR_BASE_CCY = os.environ.get('IBKR_BASE_CCY', 'HKD').upper()

ACCOUNT_TAGS = ('CashBalance', 'NetLiquidation', 'AvailableFunds',
                'BuyingPower', 'EquityWithLoanValue')

async def fetch_positions_and_summary():
    ib = IB()
    try:
        await ib.connectAsync(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=10)
        print(f"Connected to {IBKR_HOST}:{IBKR_PORT}")
    except Exception as e:
        # Honest-fail: returning ([], {}) here would make write_positions()
        # TRUNCATE bronze.ibkr_positions_live and the caller exit 0, wiping
        # the account page on every TWS-down day (weekends, daily reset).
        print(f"❌ IBKR connection failed: {e}")
        raise SystemExit(2)

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
    
    # Get account summary — keep EVERY (tag, currency) row, plus ExchangeRate.
    summary = {}
    fx_rates = {}   # {currency: 1 unit of currency = value BASE units}
    if account:
        summary['account'] = account
        for av in ib.accountValues(account=account):
            if av.tag in ACCOUNT_TAGS:
                key = f"{av.tag}_{av.currency}" if av.currency else av.tag
                summary[key] = av.value
            elif av.tag == 'ExchangeRate' and av.currency:
                try:
                    fx_rates[av.currency.upper()] = float(av.value)
                except (TypeError, ValueError):
                    pass

    ib.disconnect()
    return result, summary, fx_rates

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

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def write_fx_rates(account, fx_rates, cur):
    """Persist captured ExchangeRate rows: bronze raw + gold.fx_rates.

    IBKR ExchangeRate semantics: 1 unit of row currency = value BASE units.
    gold.fx_rates stores both (ccy -> BASE) as captured; the shared fx layer
    reads either direction, so one row per currency suffices.
    """
    from datetime import date
    n = 0
    for ccy, rate in fx_rates.items():
        if not rate or rate <= 0:
            continue
        cur.execute("""
            INSERT INTO bronze.ibkr_fx_rates (account, from_ccy, to_ccy, rate)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (account, from_ccy, to_ccy) DO UPDATE SET
                rate = EXCLUDED.rate, fetched_at = NOW()
        """, (account, ccy, IBKR_BASE_CCY, rate))
        cur.execute("""
            INSERT INTO gold.fx_rates (from_ccy, to_ccy, rate, as_of_date, source)
            VALUES (%s, %s, %s, %s, 'ibkr_account_summary')
            ON CONFLICT (from_ccy, to_ccy, as_of_date) DO UPDATE SET
                rate = EXCLUDED.rate, source = EXCLUDED.source, fetched_at = NOW()
        """, (ccy, IBKR_BASE_CCY, rate, date.today()))
        n += 1
    if n == 0:
        # Not fatal: stored daily rates in gold.fx_rates still serve
        # conversions (staleness guard there alerts after FX_MAX_AGE_DAYS).
        print("⚠️  No ExchangeRate rows in account payload — gold.fx_rates not refreshed this run")
    else:
        print(f"✅ gold.fx_rates — {n} {IBKR_BASE_CCY}-quoted pairs captured from IBKR")
    return n


def write_account_summary(summary, fx_rates, positions_count):
    if not summary:
        return
    import fx  # shared conversion layer — the ONLY way to convert
    conn = get_connection()
    cur = conn.cursor()
    account = summary.get('account', '')
    try:
        # 1) raw per-tag-per-currency rows (nothing collapsed, nothing lost)
        for key, val in summary.items():
            if key == 'account':
                continue
            tag, _, ccy = key.rpartition('_')
            num = _num(val)
            if num is None:
                continue
            cur.execute("""
                INSERT INTO bronze.ibkr_account_values (account, tag, currency, value)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (account, tag, currency) DO UPDATE SET
                    value = EXCLUDED.value, fetched_at = NOW()
            """, (account, tag, ccy or 'BASE', num))

        # 2) FX captures -> bronze.ibkr_fx_rates + gold.fx_rates
        write_fx_rates(account, fx_rates or {}, cur)

        # 3) summary row: BASE aggregate preferred (t_65d96f4a root-cause fix —
        #    was NetLiquidation_HKD segment subtotal preferred over BASE).
        net_liq = _num(summary.get('NetLiquidation_BASE'))
        if net_liq is None:
            net_liq = _num(summary.get(f'NetLiquidation_{IBKR_BASE_CCY}'))
        if net_liq is None:
            msg = ("ALERT IBKR_NETLIQ_MISSING: no NetLiquidation_BASE/"
                   f"{IBKR_BASE_CCY} row in account payload — refusing to write "
                   "an unlabeled account summary")
            print(f"❌ {msg}")
            raise SystemExit(2)
        cash_hkd = _num(summary.get('CashBalance_HKD')) or 0
        cash_usd = _num(summary.get('CashBalance_USD')) or 0
        available = _num(summary.get(f'AvailableFunds_{IBKR_BASE_CCY}'))
        if available is None:
            available = _num(summary.get('AvailableFunds_BASE')) or 0
        buying_power = _num(summary.get(f'BuyingPower_{IBKR_BASE_CCY}'))
        if buying_power is None:
            buying_power = _num(summary.get('BuyingPower_BASE')) or 0

        # 4) USD conversions through the shared layer. Missing/stale rate
        #    raises FxRateMissing -> the step fails loudly (ALERT on stdout).
        net_liq_usd, rate, fx_date = fx.to_usd(cur, net_liq, IBKR_BASE_CCY)
        available_usd, _, _ = fx.to_usd(cur, available, IBKR_BASE_CCY)
        buying_power_usd, _, _ = fx.to_usd(cur, buying_power, IBKR_BASE_CCY)
        cash_hkd_usd, _, _ = fx.to_usd(cur, cash_hkd, 'HKD')
        cash_usd_usd, _, _ = fx.to_usd(cur, cash_usd, 'USD')
        cash_total_usd = (cash_hkd_usd or 0) + (cash_usd_usd or 0)

        cur.execute("""
            INSERT INTO bronze.ibkr_account_summary
                (account, net_liquidation, cash_hkd, cash_usd, available_funds, buying_power,
                 position_count, base_currency,
                 net_liquidation_usd, available_funds_usd, buying_power_usd,
                 cash_total_usd, fx_rate, fx_date, fetched_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (account) DO UPDATE SET
                net_liquidation = EXCLUDED.net_liquidation,
                cash_hkd = EXCLUDED.cash_hkd,
                cash_usd = EXCLUDED.cash_usd,
                available_funds = EXCLUDED.available_funds,
                buying_power = EXCLUDED.buying_power,
                position_count = EXCLUDED.position_count,
                base_currency = EXCLUDED.base_currency,
                net_liquidation_usd = EXCLUDED.net_liquidation_usd,
                available_funds_usd = EXCLUDED.available_funds_usd,
                buying_power_usd = EXCLUDED.buying_power_usd,
                cash_total_usd = EXCLUDED.cash_total_usd,
                fx_rate = EXCLUDED.fx_rate,
                fx_date = EXCLUDED.fx_date,
                fetched_at = NOW()
        """, (account, net_liq, cash_hkd, cash_usd, available, buying_power,
              positions_count, IBKR_BASE_CCY,
              net_liq_usd, available_usd, buying_power_usd,
              cash_total_usd, rate, fx_date))
        conn.commit()
        print(f"✅ bronze.ibkr_account_summary — net_liq={net_liq:.2f} {IBKR_BASE_CCY} "
              f"= {net_liq_usd:.2f} USD @ {rate:.6f} ({fx_date})")
    except SystemExit:
        conn.rollback()
        conn.close()
        raise
    except Exception as e:
        conn.rollback()
        print(f"⚠️  Account summary write failed: {e}")
        raise
    finally:
        conn.close()

async def main():
    rows, summary, fx_rates = await fetch_positions_and_summary()
    for r in rows:
        print(f"  {r['ticker']:8} {r['quantity']:>10.2f} @ {r['avg_cost']:<10.2f} mv={r['market_value']:>12.2f}")
    if summary:
        print(f"  Account summary: {summary}")
    if fx_rates:
        print(f"  FX captures (to {IBKR_BASE_CCY}): {fx_rates}")
    write_positions(rows)
    write_account_summary(summary, fx_rates, len(rows))

if __name__ == "__main__":
    asyncio.run(main())
