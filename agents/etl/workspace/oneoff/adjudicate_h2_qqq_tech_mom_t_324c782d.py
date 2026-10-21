"""Adjudicate H2_QQQ_TECH_MOM_V1 (kanban t_324c782d).

Book-owner verdict for the 2026-07-08 remediation-wave siblings (e.g.
H3_VIX_TAIL_HEDGE_V1, S14_OIL_SQUEEZE_DISC_V1) was ARCHIVE; in
gold.strategy_registry the status CHECK constraint only allows
paper/live/paused/retired, so ARCHIVE maps to status='retired'.

H2_QQQ_TECH_MOM_V1 failed its OOS gates on 2026-06-18 (run 6d3b8c7b:
sharpe_oos=-0.025, max_dd_oos=-38.33%, all_risk_gates_passed=False) and was
never adjudicated. Its monthly returns (17 rows, re-based) are published in
gold.strategy_backtest_monthly_returns, but /api/strategies/<sid>/evaluation
hard-requires a registry row (backend/app/main.py:4896) -> 404.

This script:
  1. Inserts the gold.strategy_registry row with status='retired' (idempotent).
  2. Aligns gold.strategy_research status to 'rejected' (was stale
     'backtesting'), matching the sibling adjudication convention.
"""
import psycopg2

SID = "H2_QQQ_TECH_MOM_V1"

conn = psycopg2.connect(
    host="openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com",
    port=5432, dbname="aitrading", user="openclaw_user",
    password="NewStrongPasswordHere12", sslmode="require",
)
conn.autocommit = False
cur = conn.cursor()

# --- pull canonical metrics from latest verified backtest run ---------------
cur.execute("""
SELECT sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos,
       win_rate_oos, profit_factor_oos
FROM gold.strategy_backtest_runs
WHERE strategy_id = %s
ORDER BY run_number DESC, created_at DESC
LIMIT 1
""", (SID,))
sharpe, ret, dd, trades, winrate, pf = cur.fetchone()
dd_abs = abs(dd) if dd is not None else None  # registry stores positive dd

# --- 1. registry row (idempotent) --------------------------------------------
cur.execute("""
INSERT INTO gold.strategy_registry (
    strategy_id, name, asset_class, universe_tickers, frequency,
    execution_mode, status,
    sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos,
    win_rate_oos, profit_factor_oos,
    assigned_capital, in_market_capital,
    retired_at, retirement_reason, signal_mechanism,
    created_at, updated_at
) VALUES (
    %(sid)s, %(name)s, %(asset)s, %(univ)s, %(freq)s,
    'SIMULATION', 'retired',
    %(sharpe)s, %(ret)s, %(dd)s, %(trades)s,
    %(winrate)s, %(pf)s,
    10000, 0,
    now(), %(reason)s, 'none',
    now(), now()
)
ON CONFLICT (strategy_id) DO NOTHING
""", {
    "sid": SID,
    "name": "QQQ Tech Extension Momentum with Trailing Stop",
    "asset": "EQUITY ETF",
    "univ": ["QQQ"],
    "freq": "daily",
    "sharpe": sharpe, "ret": ret, "dd": dd_abs, "trades": trades,
    "winrate": winrate, "pf": pf,
    "reason": (
        "ARCHIVE per book-owner 2026-07-08 remediation wave (sibling verdict; "
        "this sid never adjudicated at the time). Gate FAIL 2026-06-18 run "
        "6d3b8c7b: sharpe_oos=-0.025, max_dd_oos=-38.33%. Registry row created "
        "2026-09-23 (kanban t_324c782d) so published monthly_returns "
        "(17 rows, re-based) are served by /api/strategies/<sid>/evaluation."
    ),
})
print(f"registry insert rowcount: {cur.rowcount}")

# --- 2. research row adjudication --------------------------------------------
cur.execute("""
UPDATE gold.strategy_research
SET status = 'rejected',
    rejection_reason = 'OOS gates FAIL 2026-06-18 (run 6d3b8c7b: sharpe_oos=-0.025, max_dd_oos=-38.33%%, all_risk_gates_passed=false). ARCHIVE verdict applied 2026-09-23 per book-owner 2026-07-08 remediation wave (kanban t_324c782d).',
    rejection_flags = ARRAY['gate_fail', 'negative_oos_sharpe', 'high_drawdown'],
    kanban_task_id = 't_324c782d',
    updated_at = now()
WHERE strategy_id = %s AND status <> 'rejected'
""", (SID,))
print(f"research update rowcount: {cur.rowcount}")

conn.commit()

# --- readback -----------------------------------------------------------------
cur.execute("""
SELECT strategy_id, status, execution_mode, sharpe_oos, returns_oos,
       max_drawdown_oos, trade_count_oos, retirement_reason IS NOT NULL
FROM gold.strategy_registry WHERE strategy_id = %s
""", (SID,))
print("registry readback:", cur.fetchone())
cur.execute("SELECT status, rejection_flags FROM gold.strategy_research WHERE strategy_id = %s", (SID,))
print("research readback:", cur.fetchone())
conn.close()
print("COMMITTED")
