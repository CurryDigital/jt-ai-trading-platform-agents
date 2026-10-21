#!/usr/bin/env python3
"""Ad-hoc verification for batch12 2026-08-05 WRITE_SIGNAL onboarding (t_56e35a73)."""
import os
import sys

sys.path.insert(0, os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"))
from db import get_connection  # noqa: E402

SIDS = ["etf_comm_trend_basket_15"]
EXPECTED = {  # sid: (n_buy, weight_sum, n_cash, freq, family, capital)
    "etf_comm_trend_basket_15": (4, 0.5424, 1, "monthly", "trend", 225000),
}
# qr_risk (t_83c6751a) raised assigned_capital $50k -> $225k so all 4 BUY legs
# are expressible with 100-share round lots; no BELOW_ONE_LOT skips expected.
# 2026-08-06 11:59 HKT: 20% concentration cap landed; rebuilds now log one
# CONCENTRATION_CAP skip for DBC (1600 -> 1500 shares, $45,296 -> $42,465).
MIN_OPEN = {"etf_comm_trend_basket_15": 4}
EXPECTED_SKIPS = {"etf_comm_trend_basket_15": {"DBC"}}
EXPECTED_SKIP_KINDS = {"etf_comm_trend_basket_15": {"DBC": "CONCENTRATION_CAP"}}

conn = get_connection()
cur = conn.cursor()
errors = []
warnings = []

print("--- ad-hoc verification: batch12 2026-08-05 ---")

cur.execute("SELECT strategy_id, status, frequency FROM gold.strategy_research WHERE strategy_id = ANY(%s)", (SIDS,))
research = {r[0]: r for r in cur.fetchall()}
print(f"strategy_research approved: {sum(1 for r in research.values() if r[1] == 'approved')}/1")
for sid in SIDS:
    if research.get(sid, (None, None))[1] != "approved":
        errors.append(f"{sid} research status {research.get(sid)}")

cur.execute("""SELECT strategy_id, sharpe_is, sharpe_oos, max_drawdown_oos, trade_count_oos,
                      turnover_oos, all_risk_gates_passed, passed_trade_count,
                      annual_pnl_2025, annual_pnl_2026
               FROM gold.strategy_backtest_runs WHERE strategy_id = ANY(%s)""", (SIDS,))
bt = {r[0]: r for r in cur.fetchall()}
print(f"backtest_runs: {len(bt)}/1")
for sid in SIDS:
    if sid not in bt:
        errors.append(f"{sid} missing backtest run")
    else:
        r = bt[sid]
        print(f"  {sid}: sharpe_is={r[1]} sharpe_oos={r[2]} dd_oos={r[3]} trades={r[4]} "
              f"turnover={r[5]} gates={r[6]} (legacy trade_count gate={r[7]}) "
              f"pnl25={r[8]} pnl26={r[9]}")
        if r[2] is None or r[3] is None or r[4] is None:
            errors.append(f"{sid} null OOS metrics")
        if float(r[1]) != 0.262 or float(r[2]) != 1.28:
            errors.append(f"{sid} sharpe mismatch vs manifest (IS 0.262 / OOS 1.28)")

cur.execute("""SELECT strategy_id, execution_mode, status, priority, signal_mechanism,
                      disable_paper_rebuild, assigned_capital, frequency,
                      array_length(universe_tickers,1), signal_file_path IS NOT NULL
               FROM gold.strategy_registry WHERE strategy_id = ANY(%s)""", (SIDS,))
reg = {r[0]: r for r in cur.fetchall()}
print(f"registry rows: {len(reg)}/1")
for sid in SIDS:
    r = reg.get(sid)
    if not r:
        errors.append(f"{sid} missing registry row")
        continue
    print(f"  {sid}: {r[1]}/{r[2]} prio={r[3]} mech={r[4]} no_rebuild={r[5]} "
          f"cap={r[6]} freq={r[7]} universe={r[8]} sigfile={r[9]}")
    if r[1] != "PAPER" or r[2] != "paper" or r[4] != "ingested" or r[5]:
        errors.append(f"{sid} registry misconfigured: {r}")
    if not r[9]:
        errors.append(f"{sid} missing signal_file_path")
    if r[3] != "EXPERIMENTAL":
        errors.append(f"{sid} priority {r[3]} != EXPERIMENTAL")
    if r[7] != EXPECTED[sid][3]:
        errors.append(f"{sid} frequency {r[7]} != {EXPECTED[sid][3]}")
    if float(r[6]) != EXPECTED[sid][5]:
        errors.append(f"{sid} assigned_capital {r[6]} != {EXPECTED[sid][5]}")

cur.execute("""SELECT strategy_id, COUNT(*) FILTER (WHERE signal_action='BUY'),
                      ROUND(SUM(score) FILTER (WHERE signal_action='BUY'), 4),
                      COUNT(*) FILTER (WHERE ticker='CASH')
               FROM gold.strategy_ticker_scores WHERE strategy_id = ANY(%s)
               GROUP BY strategy_id""", (SIDS,))
scores = {r[0]: r for r in cur.fetchall()}
for sid, (n, wsum, ncash, _, _, _) in EXPECTED.items():
    r = scores.get(sid)
    if not r:
        errors.append(f"{sid} no ticker scores")
        continue
    print(f"  scores {sid}: BUY rows={r[1]} weight_sum={r[2]} cash_rows={r[3]}")
    if r[1] != n:
        errors.append(f"{sid} expected {n} BUY rows, got {r[1]}")
    if abs(float(r[2]) - wsum * 100) > 0.5:
        errors.append(f"{sid} weight sum {r[2]} != {wsum * 100}")
    if r[3] != ncash:
        errors.append(f"{sid} expected {ncash} CASH rows, got {r[3]}")

# signal_evaluations: owned by build_signal_redesign (wipe+rebuild from
# ticker_scores). Verify each BUY ticker lands in the manifest family.
print("signal_evaluations family coverage:")
for sid, (n, _, _, _, fam, _) in EXPECTED.items():
    cur.execute("SELECT ticker FROM gold.strategy_ticker_scores "
                "WHERE strategy_id=%s AND signal_action='BUY'", (sid,))
    tickers = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT ticker, family_key FROM gold.signal_evaluations
                   WHERE ticker = ANY(%s) AND family_key = %s""", (tickers, fam))
    covered = {r[0] for r in cur.fetchall()}
    cur.execute("""SELECT DISTINCT ticker FROM gold.signal_evaluations
                   WHERE ticker = ANY(%s)""", (tickers,))
    covered_any = {r[0] for r in cur.fetchall()}
    print(f"  {sid}: {len(covered)}/{len(tickers)} in family '{fam}'; "
          f"{len(covered_any)}/{len(tickers)} in any family")
    if len(covered) < len(tickers):
        errors.append(f"{sid}: only {len(covered)}/{len(tickers)} tickers in '{fam}'")

cur.execute("SELECT COUNT(*) FROM gold.signal_evaluations")
print(f"signal_evaluations total: {cur.fetchone()[0]}")

cur.execute("""SELECT strategy_id, COUNT(*) FROM gold.paper_trades_synthetic
               WHERE strategy_id = ANY(%s) AND status='open' GROUP BY strategy_id""", (SIDS,))
pos = dict(cur.fetchall())
print(f"open paper positions: {pos}")
for sid in SIDS:
    if pos.get(sid, 0) < MIN_OPEN.get(sid, 1):
        errors.append(f"{sid} has {pos.get(sid, 0)} open positions, expected >= {MIN_OPEN.get(sid, 1)}")
warnings.append(
    "etf_comm_trend_basket_15 at $225k (t_83c6751a): all 4 BUY legs "
    "(DBC/GLD/SLV/USO) open. 20% concentration cap applied "
    "2026-08-06: DBC capped 1600->1500 shares (~18.9% of capital); the "
    "CONCENTRATION_CAP skip on rebuild days is expected behavior.")

cur.execute("""SELECT strategy_id, ticker, skip_kind FROM gold.paper_trade_skip_log
               WHERE strategy_id = ANY(%s) AND created_at::date = CURRENT_DATE
               ORDER BY strategy_id, ticker""", (SIDS,))
skips = {}
for r in cur.fetchall():
    skips.setdefault(r[0], {})[r[1]] = r[2]
print(f"skip log (today): {skips}")
for sid, want in EXPECTED_SKIPS.items():
    got = set(skips.get(sid, {}))
    if got != want:
        errors.append(f"{sid} skips {sorted(got)} != expected {sorted(want)}")

for sid, kinds in EXPECTED_SKIP_KINDS.items():
    got = skips.get(sid, {})
    for t, k in kinds.items():
        if got.get(t) != k:
            errors.append(f"{sid} skip {t} kind {got.get(t)} != expected {k}")

cur.execute("""SELECT strategy_id, ticker, signal, confidence_score
               FROM consumption.strategies_signals_current
               WHERE strategy_id = ANY(%s) ORDER BY ticker""", (SIDS,))
sigcur = cur.fetchall()
print(f"consumption.strategies_signals_current: {[(r[1], r[2]) for r in sigcur]}")

cur.execute("""SELECT strategy_id, COUNT(*) FROM consumption.signal_logs
               WHERE strategy_id = ANY(%s) GROUP BY strategy_id""", (SIDS,))
logs = dict(cur.fetchall())
print(f"consumption.signal_logs: {logs}")
for sid in SIDS:
    if logs.get(sid, 0) < 1:
        errors.append(f"{sid} no signal_logs rows")

cur.execute("SELECT id, stage, mode FROM gold.v_pipeline_ui_feed WHERE id = ANY(%s)", (SIDS,))
ui = {r[0]: (r[1], r[2]) for r in cur.fetchall()}
print(f"v_pipeline_ui_feed: {ui}")
for sid in SIDS:
    if sid not in ui:
        errors.append(f"{sid} missing from v_pipeline_ui_feed")
    elif ui[sid][1] != "PAPER_TRADING":
        errors.append(f"{sid} UI mode {ui[sid]} != PAPER_TRADING")

# Regression guard: sibling books restored after the accidental unscoped
# rebalancer run during this task (fractional-lot manual books).
cur.execute("""SELECT strategy_id, ticker FROM gold.paper_trades_synthetic
               WHERE id IN (2459, 2521, 2530, 2534) AND status='open'""")
restored = {(r[0], r[1]) for r in cur.fetchall()}
want_restored = {("etf_country_rot_10_v2", "SPY"), ("sg_stk_52wh_mom_13", "D05.SI"),
                 ("etf_tsmom_basket_07", "GLD"), ("etf_tsmom_basket_07", "SPY")}
print(f"sibling-book restore check: {len(restored & want_restored)}/4 open")
if restored != want_restored:
    errors.append(f"sibling books not fully restored: {sorted(want_restored - restored)}")

# book-level sanity: PAPER book by asset_class after batch12
cur.execute("""SELECT asset_class, COUNT(*) FROM gold.strategy_registry
               WHERE execution_mode='PAPER' AND status='paper' AND retired_at IS NULL
               GROUP BY asset_class ORDER BY 1""")
print(f"PAPER book by asset_class: {cur.fetchall()}")

conn.close()
if warnings:
    print("\nWARNINGS:")
    for w in warnings:
        print(f"  - {w}")
if errors:
    print("\nERRORS:")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
print("\nAll ad-hoc verification checks passed.")
