#!/usr/bin/env python3
"""Ad-hoc verification for batch10 2026-08-05 WRITE_SIGNAL onboarding (t_ab5f0b78)."""
import os
import sys

sys.path.insert(0, os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"))
from db import get_connection  # noqa: E402

SIDS = ["us_stk_sue_mom_01_v2", "hk_stk_52wh_mom_04",
        "etf_tsmom_basket_07", "etf_country_rot_10_v2"]
EXPECTED = {  # sid: (n_holdings, weight_sum, n_open_min)
    "us_stk_sue_mom_01_v2": (9, 1.0001),
    "hk_stk_52wh_mom_04": (10, 1.0),
    "etf_tsmom_basket_07": (9, 1.5001),
    "etf_country_rot_10_v2": (2, 0.9348),
}

conn = get_connection()
cur = conn.cursor()
errors = []

print("--- ad-hoc verification: batch10 2026-08-05 ---")

cur.execute("SELECT strategy_id, status FROM gold.strategy_research WHERE strategy_id = ANY(%s)", (SIDS,))
research = dict(cur.fetchall())
print(f"strategy_research approved: {sum(1 for v in research.values() if v == 'approved')}/4 -> {research}")
for sid in SIDS:
    if research.get(sid) != "approved":
        errors.append(f"{sid} research status {research.get(sid)}")

cur.execute("""SELECT strategy_id, sharpe_is, sharpe_oos, max_drawdown_oos, trade_count_oos,
                      turnover_oos, all_risk_gates_passed, passed_trade_count
               FROM gold.strategy_backtest_runs WHERE strategy_id = ANY(%s)""", (SIDS,))
bt = {r[0]: r for r in cur.fetchall()}
print(f"backtest_runs: {len(bt)}/4")
for sid in SIDS:
    if sid not in bt:
        errors.append(f"{sid} missing backtest run")
    else:
        r = bt[sid]
        print(f"  {sid}: sharpe_is={r[1]} sharpe_oos={r[2]} dd_oos={r[3]} trades={r[4]} "
              f"turnover={r[5]} gates={r[6]} (legacy trade_count gate={r[7]})")

cur.execute("""SELECT strategy_id, execution_mode, status, priority, signal_mechanism,
                      disable_paper_rebuild, assigned_capital, array_length(universe_tickers,1),
                      signal_file_path IS NOT NULL
               FROM gold.strategy_registry WHERE strategy_id = ANY(%s)""", (SIDS,))
reg = {r[0]: r for r in cur.fetchall()}
print(f"registry rows: {len(reg)}/4")
for sid in SIDS:
    r = reg.get(sid)
    if not r:
        errors.append(f"{sid} missing registry row")
        continue
    print(f"  {sid}: {r[1]}/{r[2]} prio={r[3]} mech={r[4]} no_rebuild={r[5]} "
          f"cap={r[6]} universe={r[7]} sigfile={r[8]}")
    if r[1] != "PAPER" or r[2] != "paper" or r[4] != "ingested" or r[5]:
        errors.append(f"{sid} registry misconfigured: {r}")
    if not r[8]:
        errors.append(f"{sid} missing signal_file_path")

cur.execute("""SELECT strategy_id, COUNT(*) FILTER (WHERE signal_action='BUY'),
                      ROUND(SUM(score) FILTER (WHERE signal_action='BUY'), 4),
                      COUNT(*) FILTER (WHERE ticker='CASH')
               FROM gold.strategy_ticker_scores WHERE strategy_id = ANY(%s)
               GROUP BY strategy_id""", (SIDS,))
scores = {r[0]: r for r in cur.fetchall()}
for sid, (n, wsum) in EXPECTED.items():
    r = scores.get(sid)
    if not r:
        errors.append(f"{sid} no ticker scores")
        continue
    print(f"  scores {sid}: BUY rows={r[1]} weight_sum={r[2]} cash_rows={r[3]}")
    if r[1] != n:
        errors.append(f"{sid} expected {n} BUY rows, got {r[1]}")
    if abs(float(r[2]) - wsum * 100) > 0.5:
        errors.append(f"{sid} weight sum {r[2]} != {wsum * 100}")

cur.execute("""SELECT family_key, COUNT(*) FROM gold.signal_evaluations
               WHERE note LIKE '%%batch10-2026-08-05%%' GROUP BY family_key""", ())
evals = dict(cur.fetchall())
print(f"signal_evaluations by family: {evals}")
cur.execute("""SELECT COUNT(*) FROM gold.signal_evaluations
               WHERE note LIKE '%%batch10-2026-08-05%%'""", ())
n_eval = cur.fetchone()[0]
# build_signal_redesign owns this table (wipe+rebuild from ticker_scores,
# DISTINCT ON (market,ticker,family) keeps highest potential). 30 holdings,
# up to 3 shadowed by higher-potential same-family rows from older strategies.
if n_eval < 27:
    errors.append(f"signal_evaluations expected >=27 batch10 rows, got {n_eval}")

cur.execute("""SELECT strategy_id, COUNT(*) FROM gold.paper_trades_synthetic
               WHERE strategy_id = ANY(%s) AND status='open' GROUP BY strategy_id""", (SIDS,))
pos = dict(cur.fetchall())
print(f"open paper positions: {pos}")
for sid in SIDS:
    if pos.get(sid, 0) < 1:
        errors.append(f"{sid} has no open paper positions")

cur.execute("""SELECT strategy_id, COUNT(*) FROM gold.paper_trade_skip_log
               WHERE strategy_id = ANY(%s) GROUP BY strategy_id""", (SIDS,))
print(f"skip log: {dict(cur.fetchall())}")

cur.execute("""SELECT strategy_id, COUNT(*) FROM consumption.strategies_signals_current
               WHERE strategy_id = ANY(%s) GROUP BY strategy_id""", (SIDS,))
print(f"consumption.strategies_signals_current: {dict(cur.fetchall())}")

cur.execute("""SELECT strategy_id, COUNT(*) FROM consumption.signal_logs
               WHERE strategy_id = ANY(%s) GROUP BY strategy_id""", (SIDS,))
print(f"consumption.signal_logs: {dict(cur.fetchall())}")

cur.execute("SELECT family_key, strategy_id, deployed FROM gold.signal_families WHERE family_key='earnings'")
print(f"earnings family: {cur.fetchone()}")

cur.execute("SELECT is_active FROM gold.asset_registry WHERE ticker='0316.HK'")
r = cur.fetchone()
print(f"0316.HK active: {r[0] if r else 'MISSING'}")
if not r or not r[0]:
    errors.append("0316.HK not active")

cur.execute("SELECT id, stage, mode FROM gold.v_pipeline_ui_feed WHERE id = ANY(%s)", (SIDS,))
ui = dict((r[0], (r[1], r[2])) for r in cur.fetchall())
print(f"v_pipeline_ui_feed: {ui}")

conn.close()
if errors:
    print("\nERRORS:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("\nAll ad-hoc verification checks passed.")
