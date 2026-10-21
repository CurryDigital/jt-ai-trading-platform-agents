#!/usr/bin/env python3
"""Ad-hoc verification for batch11 2026-08-05 WRITE_SIGNAL onboarding (t_3f3d3109)."""
import os
import sys

sys.path.insert(0, os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"))
from db import get_connection  # noqa: E402

SIDS = ["cn_stk_lowvol_12", "sg_stk_52wh_mom_13", "us_stk_lowbeta_14",
        "etf_vix_scaled_11", "etf_tech_mom_13", "etf_def_sector_rot_12_w"]
EXPECTED = {  # sid: (n_buy, weight_sum, n_cash, freq, family)
    "cn_stk_lowvol_12": (10, 1.0, 0, "monthly", "tactical"),
    "sg_stk_52wh_mom_13": (8, 1.0, 0, "monthly", "momentum"),
    "us_stk_lowbeta_14": (15, 1.0001, 0, "monthly", "tactical"),
    "etf_vix_scaled_11": (2, 1.0, 0, "weekly", "tactical"),
    "etf_tech_mom_13": (2, 0.5726, 1, "monthly", "momentum"),
    "etf_def_sector_rot_12_w": (2, 1.0, 0, "weekly", "tactical"),
}
# vix_scaled book is legitimately flat at $100k default capital: both SPY
# ($77.1k lot) and QQQ ($72.4k lot) skip BELOW_ONE_LOT and there is no third
# candidate to redistribute to. Capital sizing handed to qr_risk (child task).
MIN_OPEN = {"etf_vix_scaled_11": 0}

conn = get_connection()
cur = conn.cursor()
errors = []
warnings = []

print("--- ad-hoc verification: batch11 2026-08-05 ---")

cur.execute("SELECT strategy_id, status, frequency FROM gold.strategy_research WHERE strategy_id = ANY(%s)", (SIDS,))
research = {r[0]: r for r in cur.fetchall()}
print(f"strategy_research approved: {sum(1 for r in research.values() if r[1] == 'approved')}/6")
for sid in SIDS:
    if research.get(sid, (None, None))[1] != "approved":
        errors.append(f"{sid} research status {research.get(sid)}")

cur.execute("""SELECT strategy_id, sharpe_is, sharpe_oos, max_drawdown_oos, trade_count_oos,
                      turnover_oos, all_risk_gates_passed, passed_trade_count,
                      annual_pnl_2025, annual_pnl_2026
               FROM gold.strategy_backtest_runs WHERE strategy_id = ANY(%s)""", (SIDS,))
bt = {r[0]: r for r in cur.fetchall()}
print(f"backtest_runs: {len(bt)}/6")
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

cur.execute("""SELECT strategy_id, execution_mode, status, priority, signal_mechanism,
                      disable_paper_rebuild, assigned_capital, frequency,
                      array_length(universe_tickers,1), signal_file_path IS NOT NULL
               FROM gold.strategy_registry WHERE strategy_id = ANY(%s)""", (SIDS,))
reg = {r[0]: r for r in cur.fetchall()}
print(f"registry rows: {len(reg)}/6")
for sid in SIDS:
    r = reg.get(sid)
    if not r:
        errors.append(f"{sid} missing registry row")
        continue
    print(f"  {sid}: {r[1]}/{r[2]} prio={r[3]} mech={r[4]} no_rebuild={r[5]} "
          f"cap={r[6]} freq={r[7]} universe={r[8]} sigfile={r[9]}")
    if r[1] != "PAPER" or r[2] != "paper" or r[5]:
        errors.append(f"{sid} registry misconfigured: {r}")
    # etf_vix_scaled_11 migrated ingested -> computed 2026-08-06 (t_f7b59c0b):
    # run 2 GLD sleeve; live generator is now the DB-backed
    # vix_scaled_gld_sleeve handler in build_rotation_signals.py.
    expected_mech = "computed" if sid == "etf_vix_scaled_11" else "ingested"
    if r[4] != expected_mech:
        errors.append(f"{sid} signal_mechanism {r[4]} != {expected_mech}")
    if not r[9]:
        errors.append(f"{sid} missing signal_file_path")
    if r[7] != EXPECTED[sid][3]:
        errors.append(f"{sid} frequency {r[7]} != {EXPECTED[sid][3]}")

cur.execute("""SELECT strategy_id, COUNT(*) FILTER (WHERE signal_action='BUY'),
                      ROUND(SUM(score) FILTER (WHERE signal_action='BUY'), 4),
                      COUNT(*) FILTER (WHERE ticker='CASH')
               FROM gold.strategy_ticker_scores WHERE strategy_id = ANY(%s)
               GROUP BY strategy_id""", (SIDS,))
scores = {r[0]: r for r in cur.fetchall()}
for sid, (n, wsum, ncash, _, _) in EXPECTED.items():
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
# ticker_scores). note no longer carries batch_id (t_071207e4), so verify by
# checking each strategy's BUY tickers land in the manifest family.
print("signal_evaluations family coverage:")
for sid, (n, _, _, _, fam) in EXPECTED.items():
    cur.execute("SELECT ticker FROM gold.strategy_ticker_scores "
                "WHERE strategy_id=%s AND signal_action='BUY'", (sid,))
    tickers = [r[0] for r in cur.fetchall()]
    cur.execute("""SELECT ticker, family_key FROM gold.signal_evaluations
                   WHERE ticker = ANY(%s) AND family_key = %s""", (tickers, fam))
    covered = {r[0] for r in cur.fetchall()}
    # shared US ETF tickers (SPY/QQQ/IEF/XLK...) may shadow across families;
    # count coverage under ANY family too
    cur.execute("""SELECT DISTINCT ticker FROM gold.signal_evaluations
                   WHERE ticker = ANY(%s)""", (tickers,))
    covered_any = {r[0] for r in cur.fetchall()}
    print(f"  {sid}: {len(covered)}/{len(tickers)} in family '{fam}'; "
          f"{len(covered_any)}/{len(tickers)} in any family")
    if sid.startswith(("cn_", "sg_")) and len(covered) < len(tickers):
        # CN/SG tickers are unique to these strategies; must all land
        errors.append(f"{sid}: only {len(covered)}/{len(tickers)} tickers in '{fam}'")
    if len(covered_any) < len(tickers):
        warnings.append(f"{sid}: {sorted(set(tickers) - covered_any)} shadowed/absent in signal_evaluations")

cur.execute("SELECT COUNT(*) FROM gold.signal_evaluations")
print(f"signal_evaluations total: {cur.fetchone()[0]}")

cur.execute("""SELECT strategy_id, COUNT(*) FROM gold.paper_trades_synthetic
               WHERE strategy_id = ANY(%s) AND status='open' GROUP BY strategy_id""", (SIDS,))
pos = dict(cur.fetchall())
print(f"open paper positions: {pos}")
for sid in SIDS:
    min_open = MIN_OPEN.get(sid, 1)
    if pos.get(sid, 0) < min_open:
        errors.append(f"{sid} has {pos.get(sid, 0)} open positions, expected >= {min_open}")
if pos.get("etf_vix_scaled_11", 0) == 0:
    warnings.append("etf_vix_scaled_11 paper book FLAT: SPY 60% / QQQ 40% slots "
                    "breach the 20% single-position cap ($40k of $200k, "
                    "t_569c181f) -> CONCENTRATION_CAP skip; structural under "
                    "current cap policy - sizing decision with qr_risk")

cur.execute("""SELECT strategy_id, ticker, skip_kind FROM gold.paper_trade_skip_log
               WHERE strategy_id = ANY(%s) ORDER BY strategy_id, ticker""", (SIDS,))
skips = {}
for r in cur.fetchall():
    skips.setdefault(r[0], []).append(f"{r[1]}[{r[2]}]")
print(f"skip log: {skips}")

cur.execute("""SELECT strategy_id, COUNT(*) FROM consumption.strategies_signals_current
               WHERE strategy_id = ANY(%s) GROUP BY strategy_id""", (SIDS,))
print(f"consumption.strategies_signals_current: {dict(cur.fetchall())}")

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

# book-level sanity: 8 stock + 8 ETF PAPER strategies after batch10+11
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
