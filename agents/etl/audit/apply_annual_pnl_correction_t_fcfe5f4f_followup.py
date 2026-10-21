#!/usr/bin/env python3
"""t_fcfe5f4f: apply remaining corrections in ONE transaction.

1. hk_ipo_postlisting_drift_c1 run ecc87557: fix 2026 annual to the r2 curve value
   (0.194571; chain == returns_oos 1.1077) — undo the race overwrite of 0.2373.
2. COMM_Gold_Trend_VolTarget: set chain-validated book annuals on all 4 tied
   variant runs (2024=NULL — OOS starts 2025).
3. v_pipeline_ui_feed tiebreak: compare ABS(max_drawdown_oos) so the
   registry-aligned run wins identical-timestamp ties (flips only COMM_Gold
   50370a63 -> 744bb1b5; verified impact = 1 strategy).
All column changes audit-logged (phase='update', task_id='t_fcfe5f4f').
Idempotent: re-run plans 0 changes.
"""
import os, sys
import psycopg2

dsn = os.environ['OPENCLAW_DATABASE_URL']
if 'sslmode' not in dsn:
    dsn += ('&' if '?' in dsn else '?') + 'sslmode=require'

FIX = {
    # run_id: (strategy_id, a2024, a2025, a2026, src)
    'ecc87557-ba7d-4f77-855b-9d36b07d1809': (
        'hk_ipo_postlisting_drift_c1', 0.196407, 0.474724, 0.194571,
        'audit_c1_r2/hk_ipo_postlisting_drift_c1_qa_reproduce/ipo_pulse_C1_trade_log.csv (post-epsilon re-run, 22 trades, matches run notes 2026 +19.5pct)'),
    '744bb1b5-0a4f-47d7-b7fe-2b8a630ca0e2': (
        'COMM_Gold_Trend_VolTarget', None, 0.343785, -0.022960,
        'postbackfill lb63_vt10 (DEPLOYED variant) PV curve, OOS 2025-01-02..2026-08-18'),
    '50370a63-b44b-4499-be76-a67411824cdd': (
        'COMM_Gold_Trend_VolTarget', None, 0.373385, -0.065020,
        'postbackfill lb126_vt10 variant PV curve, OOS 2025-01-02..2026-08-18'),
    '5b4748b0-c1c6-4754-802a-a2a24ce340db': (
        'COMM_Gold_Trend_VolTarget', None, 0.517723, -0.036275,
        'postbackfill lb63_vt15 variant PV curve, OOS 2025-01-02..2026-08-18'),
    '545f6983-ae78-40e8-bf51-aa7595d5dc7e': (
        'COMM_Gold_Trend_VolTarget', None, 0.563288, -0.098480,
        'postbackfill lb126_vt15 variant PV curve, OOS 2025-01-02..2026-08-18'),
}

conn = psycopg2.connect(dsn)
conn.autocommit = False
cur = conn.cursor()

changes = 0
try:
    for run_id, (sid, a24, a25, a26, src) in FIX.items():
        cur.execute("""SELECT annual_pnl_2024, annual_pnl_2025, annual_pnl_2026, returns_oos
                       FROM gold.strategy_backtest_runs WHERE run_id=%s""", (run_id,))
        row = cur.fetchone()
        if not row:
            print(f"MISSING run {run_id}"); sys.exit(1)
        old = dict(zip(('annual_pnl_2024', 'annual_pnl_2025', 'annual_pnl_2026'), row[:3]))
        new = {'annual_pnl_2024': a24, 'annual_pnl_2025': a25, 'annual_pnl_2026': a26}
        # chain validation
        yrs = [v for v in (a24, a25, a26) if v is not None]
        chain = 1.0
        for v in yrs: chain *= (1 + v)
        roos = float(row[3])
        ok = abs(chain - 1 - roos) < 0.001
        print(f"{sid} {run_id[:8]}: chain={chain-1:+.6f} vs returns_oos={roos:+.6f} {'PASS' if ok else 'FAIL'}")
        if not ok:
            print("CHAIN CHECK FAILED — aborting"); sys.exit(1)
        for col in ('annual_pnl_2024', 'annual_pnl_2025', 'annual_pnl_2026'):
            ov, nv = old[col], new[col]
            if (ov is None and nv is None) or (ov is not None and nv is not None and abs(float(ov) - nv) < 5e-7):
                continue
            cur.execute("""INSERT INTO gold.strategy_backtest_runs_annual_pnl_audit
                (phase, task_id, strategy_id, run_id, annual_pnl_2024, annual_pnl_2025, annual_pnl_2026,
                 returns_oos, column_name, old_value, new_value, trades_sum_is_book_annual_return)
                VALUES ('update','t_fcfe5f4f',%s,%s,%s,%s,%s,%s,%s,%s,%s,false)""",
                (sid, run_id, a24, a25, a26, roos, col, ov, nv))
            changes += 1
            print(f"  audit: {col} {ov} -> {nv}")
        cur.execute(f"""UPDATE gold.strategy_backtest_runs
            SET annual_pnl_2024=%s, annual_pnl_2025=%s, annual_pnl_2026=%s,
                notes = CASE WHEN notes LIKE '%%t_fcfe5f4f chain-verified%%' THEN notes
                             ELSE COALESCE(notes,'') || ' | annual_pnl chain-verified book annuals ({src}), t_fcfe5f4f 2026-09-21' END
            WHERE run_id=%s""", (a24, a25, a26, run_id))

    # --- view tiebreak fix ---
    cur.execute("SELECT pg_get_viewdef('gold.v_pipeline_ui_feed'::regclass, true)")
    vdef = cur.fetchone()[0]
    old_expr = "NOT strategy_backtest_runs.max_drawdown_oos IS DISTINCT FROM reg_match.max_drawdown_oos"
    new_expr = "NOT abs(strategy_backtest_runs.max_drawdown_oos) IS DISTINCT FROM abs(reg_match.max_drawdown_oos)"
    if new_expr in vdef:
        print("view tiebreak already ABS — no change")
    elif old_expr in vdef:
        cur.execute("CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS " + vdef.replace(old_expr, new_expr))
        print("view tiebreak updated to ABS() comparison")
    else:
        print("VIEW DEF PATTERN NOT FOUND — aborting"); sys.exit(1)

    conn.commit()
    print(f"\nCOMMITTED. audit rows written: {changes}")
except Exception:
    conn.rollback()
    raise
finally:
    conn.close()
