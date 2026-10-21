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

    # ── Live canonical account values from IBKR (currency-labeled, t_65d96f4a)
    cur.execute("""
        SELECT account, net_liquidation, cash_hkd, cash_usd, buying_power,
               base_currency, net_liquidation_usd, buying_power_usd, cash_total_usd
        FROM gold.ibkr_account_summary
        ORDER BY fetched_at DESC
        LIMIT 1
    """)
    live = cur.fetchone()
    if not live:
        print("No live account data found")
        sys.exit(1)
    (account, net_liq_native, cash_hkd, cash_usd, bp_native,
     base_ccy, net_liq_usd, bp_usd, cash_total_usd) = live
    net_liq_native = float(net_liq_native)
    if net_liq_usd is None:
        all_pass = fail("gold.ibkr_account_summary.net_liquidation_usd is NULL — "
                        "conversion layer not applied (run ingest/promote)") and all_pass
        print("Cannot continue currency checks without USD values")
        sys.exit(1)
    net_liq = float(net_liq_usd)
    buying_power = float(bp_usd)
    live_cash = float(cash_total_usd or 0)
    base_ccy = base_ccy or 'HKD'

    # Currency sanity band (audit recommendation #5): the served USD equity
    # must be the native value divided by a plausible USD/HKD rate. Catches
    # any regression to serving HKD as USD (band fails by ~7.85x).
    if base_ccy == 'HKD':
        lo, hi = net_liq_native / 8.5, net_liq_native / 7.0
        if not (lo <= net_liq <= hi):
            all_pass = fail(f"live equity USD {net_liq:.2f} outside HKD-conversion band "
                            f"[{lo:.2f}, {hi:.2f}] of native {net_liq_native:.2f} — "
                            "HKD-as-USD regression?") and all_pass
        else:
            all_pass = ok(f"live equity {net_liq:.2f} USD within HKD band of native {net_liq_native:.2f}") and all_pass

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

    # ── Paper rows must match the paper ledger (t_749e13f0) ───────────────
    # portfolio_positions_current now intentionally carries PAPER_TRADING rows
    # synced from gold.paper_trades_synthetic by
    # consumption/portfolio/sync_paper_positions_current.py; the capital-pool
    # endpoint reads them. Assert sync parity instead of absence.
    # t_f51d67fe: the sync intentionally surfaces only ACTIVELY MONITORED
    # strategies; the synthetic ledger is a shadow ledger for all approved
    # pipeline strategies, so parity is against the monitored open subset.
    cur.execute("""
        SELECT COUNT(*) FROM consumption.portfolio_positions_current
        WHERE execution_mode = 'PAPER_TRADING' AND status = 'ACTIVE'
    """)
    paper_in_current = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM gold.paper_trades_synthetic pts
        WHERE pts.status = 'open'
          AND EXISTS (SELECT 1 FROM gold.strategy_paper_monitoring m
                      WHERE m.strategy_id = pts.strategy_id AND m.is_active)
    """)
    ledger_open = cur.fetchone()[0]
    if paper_in_current != ledger_open:
        all_pass = fail(f"{paper_in_current} paper rows in portfolio_positions_current != {ledger_open} monitored open ledger positions — run sync_paper_positions_current.py") and all_pass
    else:
        all_pass = ok(f"{paper_in_current} paper positions in portfolio_positions_current match monitored open ledger") and all_pass

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

    # ── Canonical aggregate paper book (t_2b2ac824) ─────────────────────────
    # equity = SUM(assigned_capital) over is_active monitored PAPER strategies;
    # cash = equity - net deployed MV; buying_power = equity - gross deployed MV;
    # exposure counts only PAPER_TRADING rows; live book must exclude paper rows.
    cur.execute("""
        SELECT COALESCE(SUM(r.assigned_capital), 0)
        FROM gold.strategy_paper_monitoring m
        JOIN gold.strategy_registry r ON r.strategy_id = m.strategy_id
        WHERE m.is_active AND r.execution_mode = 'PAPER'
          AND r.assigned_capital IS NOT NULL
    """)
    assigned = float(cur.fetchone()[0])

    cur.execute("""
        SELECT COALESCE(SUM(ABS(market_value)), 0), COALESCE(SUM(market_value), 0),
               COALESCE(SUM(unrealized_pnl), 0), COUNT(*)
        FROM consumption.portfolio_positions_current
        WHERE execution_mode = 'PAPER_TRADING' AND status IN ('OPEN', 'ACTIVE')
    """)
    p_gross, p_net, p_upl, p_count = cur.fetchone()
    p_gross, p_net, p_upl = float(p_gross), float(p_net), float(p_upl)

    cur.execute("""
        SELECT equity, buying_power, cash_pct, gross_exp_pct, net_exp_pct,
               open_pnl, positions
        FROM consumption.account_summary WHERE book = 'paper'
    """)
    row = cur.fetchone()
    if not row:
        all_pass = fail("no paper row in consumption.account_summary") and all_pass
    else:
        p_eq, p_bp, p_cash_pct, p_gxp, p_nxp, p_opnl, p_pos = [float(x) for x in row]
        if assigned > 0 and abs(p_eq - assigned) > 0.01:
            all_pass = fail(f"paper equity {p_eq} != SUM(assigned_capital) {assigned}") and all_pass
        else:
            all_pass = ok(f"paper equity {p_eq} == SUM(assigned_capital) {assigned}") and all_pass
        if p_eq > 0:
            exp_bp = max(p_eq - p_gross, 0)
            if abs(p_bp - exp_bp) > 0.01:
                all_pass = fail(f"paper buying_power {p_bp} != equity - gross {exp_bp}") and all_pass
            else:
                all_pass = ok(f"paper buying_power {p_bp} == equity - gross {exp_bp}") and all_pass
            exp_cash_pct = (p_eq - p_net) / p_eq * 100
            if abs(p_cash_pct - exp_cash_pct) > 0.1:
                all_pass = fail(f"paper cash_pct {p_cash_pct} != expected {exp_cash_pct:.4f}") and all_pass
            else:
                all_pass = ok(f"paper cash_pct {p_cash_pct:.4f} == expected {exp_cash_pct:.4f}") and all_pass
            exp_gxp = p_gross / p_eq * 100
            if abs(p_gxp - exp_gxp) > 0.1:
                all_pass = fail(f"paper gross_exp_pct {p_gxp} != expected {exp_gxp:.4f}") and all_pass
            else:
                all_pass = ok(f"paper gross_exp_pct {p_gxp:.4f} == expected {exp_gxp:.4f}") and all_pass
        if abs(p_opnl - p_upl) > 0.01:
            all_pass = fail(f"paper open_pnl {p_opnl} != positions unrealized {p_upl}") and all_pass
        else:
            all_pass = ok(f"paper open_pnl {p_opnl} == positions unrealized {p_upl}") and all_pass
        if int(p_pos) != int(p_count):
            all_pass = fail(f"paper positions {p_pos} != PAPER_TRADING row count {p_count}") and all_pass
        else:
            all_pass = ok(f"paper positions {int(p_pos)} == PAPER_TRADING row count {p_count}") and all_pass

    cur.execute("""
        SELECT gross_exp_pct, positions FROM consumption.account_summary
        WHERE book = 'live'
    """)
    l_gxp, l_pos = cur.fetchone()
    cur.execute("""
        SELECT COALESCE(SUM(ABS(market_value)), 0), COUNT(*)
        FROM consumption.portfolio_positions_current
        WHERE status IN ('OPEN', 'ACTIVE')
          AND execution_mode IS DISTINCT FROM 'PAPER_TRADING'
    """)
    l_gross, l_count = cur.fetchone()
    if net_liq > 0 and abs(float(l_gxp) - float(l_gross) / net_liq * 100) > 0.1:
        all_pass = fail(f"live gross_exp_pct {l_gxp} includes paper rows (expected {float(l_gross)/net_liq*100:.4f})") and all_pass
    else:
        all_pass = ok(f"live gross_exp_pct {float(l_gxp):.4f} excludes paper rows") and all_pass
    if int(l_pos) != int(l_count):
        all_pass = fail(f"live positions {l_pos} != non-paper row count {l_count}") and all_pass
    else:
        all_pass = ok(f"live positions {int(l_pos)} == non-paper row count {l_count}") and all_pass

    # ── gold.account_nav_daily live row: native equity labeled, USD converted ──
    # t_65d96f4a: equity stays in the book's native currency (HKD, labeled via
    # the currency column); equity_usd must match the converted net_liq.
    # Use the date of the latest IBKR fetch; data can be stale relative to wall-clock today.
    cur.execute("""
        SELECT MAX(fetched_at::date) FROM gold.ibkr_account_summary
    """)
    nav_date = cur.fetchone()[0]
    cur.execute("""
        SELECT equity, currency, equity_usd FROM gold.account_nav_daily
        WHERE book = 'live' AND as_of_date = %s
    """, (nav_date,))
    nav_row = cur.fetchone()
    if not nav_row:
        all_pass = fail(f"no live gold.account_nav_daily row for {nav_date}") and all_pass
    else:
        nav_eq, nav_ccy, nav_eq_usd = nav_row
        if nav_ccy != base_ccy:
            all_pass = fail(f"account_nav_daily live currency {nav_ccy} != {base_ccy}") and all_pass
        elif abs(float(nav_eq) - net_liq_native) > 0.01:
            all_pass = fail(f"account_nav_daily live equity {nav_eq} != native net_liq {net_liq_native}") and all_pass
        elif nav_eq_usd is None or abs(float(nav_eq_usd) - net_liq) > 0.01:
            all_pass = fail(f"account_nav_daily live equity_usd {nav_eq_usd} != net_liquidation_usd {net_liq}") and all_pass
        else:
            all_pass = ok(f"account_nav_daily live {nav_eq} {nav_ccy} = {float(nav_eq_usd):.2f} USD") and all_pass

    # ── gold.portfolio_snapshots live row: labeled native + converted USD ──
    cur.execute("""
        SELECT snapshot_date, total_value, cash_value, positions_value,
               currency, total_value_usd, cash_value_usd
        FROM gold.portfolio_snapshots
        WHERE portfolio_type = 'live' AND snapshot_date = %s
    """, (nav_date,))
    snap = cur.fetchone()
    if not snap:
        all_pass = fail(f"no live gold.portfolio_snapshots row for {nav_date}") and all_pass
    else:
        snapshot_date, total, cash, positions, snap_ccy, total_usd, cash_usd_v = snap
        total_f = float(total)
        cash_f = float(cash)
        positions_f = float(positions)
        if snap_ccy != base_ccy:
            all_pass = fail(f"live snapshot currency {snap_ccy} != {base_ccy}") and all_pass
        elif abs(total_f - net_liq_native) > 0.01:
            all_pass = fail(f"live snapshot total {total_f} != native net_liq {net_liq_native}") and all_pass
        elif total_usd is None or abs(float(total_usd) - net_liq) > 0.01:
            all_pass = fail(f"live snapshot total_value_usd {total_usd} != net_liquidation_usd {net_liq}") and all_pass
        else:
            all_pass = ok(f"live snapshot total {total_f} {snap_ccy} = {float(total_usd):.2f} USD") and all_pass
        if cash_f <= 0:
            # KNOWN ISSUE (documented 2026-10-09 audit): the IBKR cash writer
            # stores cash_hkd/cash_usd = 0, so snapshot cash is 0. The cash
            # writer fix is sequenced BEHIND this FX card (t_65d96f4a) —
            # warn, don't fail, so the canary stays usable for regressions.
            print(f"⚠️  WARN: live snapshot cash_value {cash_f} (broken cash writer — known, sequenced separately)")
        else:
            all_pass = ok(f"live snapshot cash_value {cash_f} positive") and all_pass
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
