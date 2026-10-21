#!/usr/bin/env python3
"""Flatten residual GLD -50 short on DUP825942 — kanban t_72843934.

User-approved 2026-10-15. Same conditions as 2026-10-09 (t_7d69ab61), with the
10-09 non-fill cause addressed: GLD's +0.5% marketable-limit cap (381.59 vs
prior close 379.69) was run past at the open (mkt ~384.46). This order uses a
wider still-capped marketable limit: max(2026-10-14 close 375.99, UAT mark
376.39978025) * 1.02 = 383.93.

Path: DIRECT GATEWAY SCRIPT (127.0.0.1:14002 paper tunnel, clientId 78).
The guarded backend POST /api/ib/place-order path is still MKT-only for this
flow (rebuild_paper_positions.py fires order_type='MKT'; 10-09 comment records
ib_service.py:391-395 MarketOrder-only), so it cannot satisfy LMT/DAY/RTH.

Spec: BUY 50 GLD LMT 383.93 DAY RTH-only, orderRef=RECON_FLATTEN_t_72843934,
strategy_id documentation OPS_RECON, idempotency key recon-flatten-t_72843934-GLD.
Single submission, no retry. Pre-submit guard refuses unless open orders == 0
and live positions are exactly GLD -50.
"""
import asyncio
asyncio.set_event_loop(asyncio.new_event_loop())  # py3.14 eventkit workaround
from ib_insync import IB, Stock, LimitOrder
import sys, json, datetime

HOST, PORT, CLIENT_ID = "127.0.0.1", 14002, 78
ACCT = "DUP825942"
SYM, QTY, LMT = "GLD", 50, 383.93
ORDER_REF = "RECON_FLATTEN_t_72843934"
IDEM = "recon-flatten-t_72843934-GLD"
OUT = "/home/ubuntu/.hermes/profiles/qr_etl/workspace/uat_gld_flatten_t_72843934_result.json"


def live_positions(ib):
    pos = []
    for p in ib.reqPositions():
        if p.account == ACCT and float(p.position) != 0:
            pos.append({"symbol": p.contract.symbol, "qty": float(p.position),
                        "avg_cost": float(p.avgCost), "currency": p.contract.currency})
    return pos


def main():
    ib = IB()
    ib.connect(HOST, PORT, clientId=CLIENT_ID, timeout=15)
    try:
        accounts = ib.managedAccounts()
        print("managed accounts:", accounts)
        if ACCT not in accounts:
            print(f"FATAL: expected account {ACCT} not in managed accounts — refusing to trade")
            sys.exit(2)
        acct_vals = [v for v in ib.accountValues(ACCT)
                     if v.tag in ("NetLiquidation", "TotalCashValue", "GrossPositionValue")]
        print("account_values:", [(v.tag, v.value, v.currency) for v in acct_vals])

        existing = ib.reqAllOpenOrders()
        print("open_orders_count:", len(existing))
        if existing:
            print("FATAL: open orders exist — pre-check violated, refusing:", existing)
            sys.exit(2)
        pos = live_positions(ib)
        print("positions_nonzero:", json.dumps(pos))
        if not (len(pos) == 1 and pos[0]["symbol"] == SYM and pos[0]["qty"] == -float(QTY)):
            print("FATAL: positions are not exactly GLD -50 — refusing to trade")
            sys.exit(2)

        contract = Stock(SYM, "SMART", "USD")
        ib.qualifyContracts(contract)
        order = LimitOrder("BUY", QTY, LMT)
        order.account = ACCT
        order.tif = "DAY"
        order.outsideRth = False
        order.orderRef = ORDER_REF
        trade = ib.placeOrder(contract, order)
        ib.sleep(3)  # allow status callback; NO retry beyond this single submit
        result = {
            "ts_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "account": ACCT, "symbol": SYM, "qty": QTY, "limit": LMT,
            "limit_basis": "max(2026-10-14 close 375.99, UAT mark 376.39978025) * 1.02",
            "idempotency_key": IDEM, "order_ref": ORDER_REF, "strategy_id": "OPS_RECON",
            "ib_order_id": trade.order.orderId, "perm_id": trade.order.permId,
            "status": trade.orderStatus.status, "filled": trade.orderStatus.filled,
            "remaining": trade.orderStatus.remaining,
            "tif": trade.order.tif, "outsideRth": trade.order.outsideRth,
            "log": [str(e) for e in trade.log],
        }
        print(json.dumps(result, indent=2))
        with open(OUT, "w") as f:
            json.dump(result, f, indent=2)
        print("WROTE", OUT)
        if trade.orderStatus.status in ("Cancelled", "Inactive", "ApiCancelled"):
            print(f"FATAL: {SYM} order not accepted ({trade.orderStatus.status}) — STOP, no retry")
            sys.exit(2)
    finally:
        ib.disconnect()


if __name__ == "__main__":
    main()
