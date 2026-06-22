#!/usr/bin/env python3
"""
Bronze Ingestion: IBKR Orders + Executions via TWS API (ib_insync)
Tables:
  bronze.ibkr_orders — open orders + execution fills from IBKR
Source: IBKR TWS API via local SSH tunnel (127.0.0.1:14002)
Env:   IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID
"""
import sys, os, json
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import asyncio

# ib_insync/eventkit eagerly grabs the event loop at import time.
# Python 3.14+ disallows get_event_loop() in non-main threads / before a loop exists.
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from ib_insync import IB, util
from db import get_connection
from datetime import datetime, timezone

IBKR_HOST = os.environ.get('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.environ.get('IBKR_PORT', 14002))
IBKR_CLIENT_ID = int(os.environ.get('IBKR_CLIENT_ID', 98))


async def connect_ib():
    ib = IB()
    try:
        await ib.connectAsync(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID, timeout=15)
        print(f"Connected to {IBKR_HOST}:{IBKR_PORT}")
        return ib
    except Exception as e:
        print(f"⚠️  IBKR connection failed: {e}")
        return None


async def fetch_open_orders(ib):
    """Fetch all open orders via reqOpenOrdersAsync."""
    orders = await ib.reqOpenOrdersAsync()
    results = []
    for o in orders:
        contract = o.contract
        # Determine status from orderState if available
        status = getattr(o, 'orderState', None)
        status_str = status.status if status else 'Open'

        results.append({
            'account': o.account or '',
            'order_id': o.orderId,
            'client_id': o.clientId,
            'perm_id': o.permId,
            'ticker': contract.symbol if contract else '',
            'action': o.action,
            'quantity': o.totalQuantity,
            'order_type': o.orderType,
            'limit_price': o.lmtPrice if o.lmtPrice else None,
            'aux_price': o.auxPrice if o.auxPrice else None,
            'tif': o.tif,
            'status': status_str,
            'filled': getattr(o, 'filledQuantity', 0) or 0,
            'remaining': o.totalQuantity - (getattr(o, 'filledQuantity', 0) or 0),
            'avg_fill_price': None,
            'last_fill_price': None,
            'commission': None,
            'realized_pnl': None,
            'submit_time': None,
            'execution_time': None,
            'gtc': o.tif == 'GTC',
            'exchange': contract.exchange if contract else '',
            'currency': contract.currency if contract else '',
            'con_id': contract.conId if contract else None,
            'local_symbol': contract.localSymbol if contract else '',
            'notes': 'Source: open_orders',
            'raw_json': json.dumps({
                'order': util.dataclassAsDict(o) if hasattr(util, 'dataclassAsDict') else str(o),
                'contract': util.dataclassAsDict(contract) if contract and hasattr(util, 'dataclassAsDict') else str(contract),
            }),
        })
    return results


async def fetch_executions(ib):
    """Fetch today's executions via reqExecutionsAsync."""
    fills = await ib.reqExecutionsAsync()
    results = []

    for fill in fills:
        exec_detail = fill.execution
        contract = fill.contract
        commission = fill.commissionReport

        # Parse execution time: IB format is typically "20260513 09:30:00"
        exec_time_str = exec_detail.time if exec_detail else None
        exec_time = None
        if exec_time_str:
            try:
                if ' ' in exec_time_str and '-' not in exec_time_str:
                    exec_time = datetime.strptime(exec_time_str, "%Y%m%d %H:%M:%S").replace(tzinfo=timezone.utc)
                else:
                    exec_time = datetime.fromisoformat(exec_time_str.replace(' ', 'T')).replace(tzinfo=timezone.utc)
            except Exception:
                exec_time = None

        results.append({
            'account': exec_detail.acctNumber if exec_detail else '',
            'order_id': exec_detail.orderId if exec_detail else None,
            'client_id': exec_detail.clientId if exec_detail else None,
            'perm_id': exec_detail.permId if exec_detail else None,
            'ticker': contract.symbol if contract else '',
            'action': exec_detail.side if exec_detail else '',
            'quantity': abs(exec_detail.shares) if exec_detail else 0,
            'order_type': '',
            'limit_price': None,
            'aux_price': None,
            'tif': '',
            'status': 'Filled',
            'filled': abs(exec_detail.shares) if exec_detail else 0,
            'remaining': 0,
            'avg_fill_price': exec_detail.price if exec_detail else None,
            'last_fill_price': exec_detail.price if exec_detail else None,
            'commission': commission.commission if commission else None,
            'realized_pnl': commission.realizedPNL if commission else None,
            'submit_time': None,
            'execution_time': exec_time,
            'gtc': False,
            'exchange': contract.exchange if contract else '',
            'currency': contract.currency if contract else '',
            'con_id': contract.conId if contract else None,
            'local_symbol': contract.localSymbol if contract else '',
            'notes': 'Source: executions',
            'raw_json': json.dumps({
                'execution': util.dataclassAsDict(exec_detail) if exec_detail and hasattr(util, 'dataclassAsDict') else str(exec_detail),
                'contract': util.dataclassAsDict(contract) if contract and hasattr(util, 'dataclassAsDict') else str(contract),
                'commission': util.dataclassAsDict(commission) if commission and hasattr(util, 'dataclassAsDict') else str(commission),
            }),
        })
    return results


def upsert_orders(rows):
    if not rows:
        print("No orders to upsert")
        return 0

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    for r in rows:
        try:
            cur.execute("""
                INSERT INTO bronze.ibkr_orders
                    (account, order_id, client_id, perm_id, ticker, action, quantity,
                     order_type, limit_price, aux_price, tif, status, filled, remaining,
                     avg_fill_price, last_fill_price, commission, realized_pnl,
                     submit_time, execution_time, gtc, exchange, currency, con_id,
                     local_symbol, notes, raw_json, fetched_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (account, order_id, perm_id) DO UPDATE SET
                    status = EXCLUDED.status,
                    filled = EXCLUDED.filled,
                    remaining = EXCLUDED.remaining,
                    avg_fill_price = EXCLUDED.avg_fill_price,
                    last_fill_price = EXCLUDED.last_fill_price,
                    commission = EXCLUDED.commission,
                    realized_pnl = EXCLUDED.realized_pnl,
                    execution_time = EXCLUDED.execution_time,
                    notes = EXCLUDED.notes,
                    raw_json = EXCLUDED.raw_json,
                    fetched_at = NOW()
            """, (
                r['account'], r['order_id'], r['client_id'], r['perm_id'],
                r['ticker'], r['action'], r['quantity'], r['order_type'],
                r['limit_price'], r['aux_price'], r['tif'], r['status'],
                r['filled'], r['remaining'], r['avg_fill_price'], r['last_fill_price'],
                r['commission'], r['realized_pnl'], r['submit_time'], r['execution_time'],
                r['gtc'], r['exchange'], r['currency'], r['con_id'],
                r['local_symbol'], r['notes'], r['raw_json'],
            ))
            inserted += 1
        except Exception as e:
            print(f"    Upsert error order_id={r.get('order_id')}: {e}")

    conn.commit()
    conn.close()
    return inserted


async def main():
    ib = await connect_ib()
    if not ib:
        return 1

    # Fetch open orders
    open_orders = await fetch_open_orders(ib)
    print(f"Open orders fetched: {len(open_orders)}")

    # Fetch executions (fills)
    executions = await fetch_executions(ib)
    print(f"Executions fetched: {len(executions)}")

    ib.disconnect()

    # Combine and deduplicate by (account, order_id, perm_id)
    seen = set()
    all_rows = []
    for r in open_orders + executions:
        key = (r['account'], r['order_id'], r['perm_id'])
        if key not in seen:
            seen.add(key)
            all_rows.append(r)

    inserted = upsert_orders(all_rows)
    print(f"✅ bronze.ibkr_orders — {inserted} rows upserted ({len(open_orders)} open, {len(executions)} executions)")
    return 0


if __name__ == "__main__":
    exit_code = loop.run_until_complete(main())
    sys.exit(exit_code)
