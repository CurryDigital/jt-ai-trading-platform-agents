#!/usr/bin/env python3
"""Verification tests for command-center / account_summary fix.

Exit 0 if all assertions pass, non-zero with printed failures.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
from db import get_connection

def fail(msg):
    print(f"❌ FAIL: {msg}")
    return False

def ok(msg):
    print(f"✅ {msg}")
    return True

def main():
    all_pass = True
    conn = get_connection()
    cur = conn.cursor()

    # ── Live canonical account values from IBKR ─────────────────────────────
    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd, buying_power
        FROM gold.ibkr_account_summary
        ORDER BY fetched_at DESC
        LIMIT 1
    """)
    live = cur.fetchone()
    if not live:
        print("No live account data found")
        sys.exit(1)
    account, net_liq, cash_hkd, cash_usd, buying_power = live
    net_liq = float(net_liq)
    buying_power = float(buying_power)
    live_cash = float((cash_hkd or 0) + (cash_usd or 0))

    # ── consumption.account_summary live book ───────────────────────────────
    cur.execute("SELECT * FROM consumption.account_summary WHERE book = 'live'")
    live_summary = cur.fetchone()
    if not live_summary:
        print("No live account_summary row")
        sys.exit(1)

    cols = [d[0] for d in cur.description]
    s = dict(zip(cols, live_summary))

    if abs(float(s['equity']) - net_liq) > 0.01:
        all_pass = fail(f"live equity {s['equity']} != net_liquidation {net_liq}") and all_pass
    else:
        all_pass = ok(f"live equity {s['equity']} == net_liquidation {net_liq}") and all_pass

    expected_cash_pct = live_cash / net_liq * 100 if net_liq else 0
    if abs(float(s['cash_pct']) - expected_cash_pct) > 0.1:
        all_pass = fail(f"live cash_pct {s['cash_pct']} != expected {expected_cash_pct:.4f}") and all_pass
    else:
        all_pass = ok(f"live cash_pct {s['cash_pct']:.4f} == expected {expected_cash_pct:.4f}") and all_pass

    if abs(float(s['buying_power']) - buying_power) > 0.01:
        all_pass = fail(f"live buying_power {s['buying_power']} != {buying_power}") and all_pass
    else:
        all_pass = ok(f"live buying_power {s['buying_power']} == {buying_power}") and all_pass

    # ── Live positions separated from paper positions ───────────────────────
    cur.execute("""
        SELECT COUNT(*) FROM consumption.portfolio_positions_current
        WHERE execution_mode = 'PAPER_TRADING'
    """)
    paper_in_current = cur.fetchone()[0]
    if paper_in_current > 0:
        all_pass = fail(f"{paper_in_current} paper positions still in portfolio_positions_current") and all_pass
    else:
        all_pass = ok("no paper positions in portfolio_positions_current") and all_pass

    cur.execute("""
        SELECT COUNT(*) FROM consumption.portfolio_positions_paper
        WHERE execution_mode IN ('LIVE_TRADING', 'MANUAL', 'ibkr')
    """)
    live_in_paper = cur.fetchone()[0]
    if live_in_paper > 0:
        all_pass = fail(f"{live_in_paper} live/manual positions in portfolio_positions_paper") and all_pass
    else:
        all_pass = ok("no live/manual positions in portfolio_positions_paper") and all_pass

    cur.execute("""
        SELECT COUNT(*) FROM consumption.portfolio_positions_current
        WHERE execution_mode = 'LIVE_TRADING'
    """)
    live_count = cur.fetchone()[0]
    if live_count == 0:
        all_pass = fail("no live positions in portfolio_positions_current") and all_pass
    else:
        all_pass = ok(f"{live_count} live position(s) in portfolio_positions_current") and all_pass

    cur.execute("""
        SELECT COUNT(*) FROM consumption.portfolio_positions_paper
        WHERE execution_mode = 'PAPER_TRADING'
    """)
    paper_count = cur.fetchone()[0]
    if paper_count == 0:
        all_pass = fail("no paper positions in portfolio_positions_paper") and all_pass
    else:
        all_pass = ok(f"{paper_count} paper position(s) in portfolio_positions_paper") and all_pass

    # ── Short market values must be negative ────────────────────────────────
    cur.execute("""
        SELECT ticker, market_value FROM consumption.portfolio_positions_paper
        WHERE side = 'SHORT' AND market_value >= 0
    """)
    bad_shorts = cur.fetchall()
    if bad_shorts:
        all_pass = fail(f"shorts with non-negative market_value: {bad_shorts}") and all_pass
    else:
        all_pass = ok("paper short positions carry negative market_value") and all_pass

    cur.execute("""
        SELECT ticker, market_value FROM consumption.portfolio_positions_current
        WHERE side = 'SHORT' AND market_value >= 0
    """)
    bad_shorts = cur.fetchall()
    if bad_shorts:
        all_pass = fail(f"live shorts with non-negative market_value: {bad_shorts}") and all_pass
    else:
        all_pass = ok("live short positions carry negative market_value") and all_pass

    # ── gross_exp_pct >= net_exp_pct when shorts are present ─────────────────
    cur.execute("""
        SELECT gross_exp_pct, net_exp_pct FROM consumption.account_summary
        WHERE book = 'paper'
    """)
    paper = cur.fetchone()
    if paper and float(paper[1]) > float(paper[0]):
        all_pass = fail(f"paper net_exp_pct {paper[1]} > gross_exp_pct {paper[0]}") and all_pass
    else:
        all_pass = ok("paper net_exp_pct <= gross_exp_pct") and all_pass

    # ── gold.account_nav_daily live row uses net_liquidation, not snapshot ────
    # Use the date of the latest IBKR fetch; data can be stale relative to wall-clock today.
    cur.execute("""
        SELECT MAX(fetched_at::date) FROM gold.ibkr_account_summary
    """)
    nav_date = cur.fetchone()[0]
    cur.execute("""
        SELECT equity FROM gold.account_nav_daily
        WHERE book = 'live' AND as_of_date = %s
    """, (nav_date,))
    nav_row = cur.fetchone()
    if not nav_row:
        all_pass = fail(f"no live gold.account_nav_daily row for {nav_date}") and all_pass
    elif abs(float(nav_row[0]) - net_liq) > 0.01:
        all_pass = fail(f"gold.account_nav_daily live equity {nav_row[0]} != net_liquidation {net_liq}") and all_pass
    else:
        all_pass = ok(f"gold.account_nav_daily live equity {nav_row[0]} == net_liquidation {net_liq}") and all_pass

    # ── gold.portfolio_snapshots live row includes cash and equals net_liquidation ──
    cur.execute("""
        SELECT snapshot_date, total_value, cash_value, positions_value
        FROM gold.portfolio_snapshots
        WHERE portfolio_type = 'live' AND snapshot_date = %s
    """, (nav_date,))
    snap = cur.fetchone()
    if not snap:
        all_pass = fail(f"no live gold.portfolio_snapshots row for {nav_date}") and all_pass
    else:
        snapshot_date, total, cash, positions = snap
        total_f = float(total)
        cash_f = float(cash)
        positions_f = float(positions)
        if abs(total_f - net_liq) > 0.01:
            all_pass = fail(f"live snapshot total {total_f} != net_liquidation {net_liq}") and all_pass
        else:
            all_pass = ok(f"live snapshot total {total_f} == net_liquidation {net_liq}") and all_pass
        if cash_f <= 0:
            all_pass = fail(f"live snapshot cash_value {cash_f} is not positive") and all_pass
        else:
            all_pass = ok(f"live snapshot cash_value {cash_f} > 0") and all_pass
        if abs(total_f - (cash_f + positions_f)) > 0.01:
            all_pass = fail(f"live snapshot total {total_f} != cash {cash_f} + positions {positions_f}") and all_pass
        else:
            all_pass = ok(f"live snapshot total {total_f} == cash {cash_f} + positions {positions_f}") and all_pass

    cur.close()
    conn.close()

    if all_pass:
        print("\n✅ All command-center verification checks passed.")
        sys.exit(0)
    else:
        print("\n❌ Some verification checks failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
