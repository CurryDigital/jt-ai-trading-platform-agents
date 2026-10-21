-- t_fcfe5f4f: annual_pnl_* correction on 8 feed strategies (2026-09-21)
-- *** SUPERSEDED — DO NOT RE-APPLY ***
-- This plan was applied 2026-09-21 ~01:30 UTC, then a follow-up correction
-- (apply_annual_pnl_correction_t_fcfe5f4f_followup.py, same dir) fixed:
--   * hk_ipo_postlisting_drift_c1: new run ecc87557 (t_b97b7340 float-epsilon
--     re-run) landed mid-task; 2026 annual reverted 0.2373 -> 0.194571
--     (chain == returns_oos 1.1077).
--   * COMM_Gold_Trend_VolTarget: annuals set per-variant on ALL FOUR tied
--     2026-08-18 runs (deployed lb63_vt10 744bb1b5: +0.343785/-0.022960);
--     v_pipeline_ui_feed tiebreak changed to ABS(max_drawdown_oos) so the
--     registry-aligned deployed run wins the created_at tie.
-- Original header follows for provenance.
--
-- Replaces corrupted trade-sum / IS-year annual_pnl_YYYY values on the LATEST
-- run per strategy with book-level equity-curve calendar-year returns.
-- Convention: chained PV-ratio / return-attribution; (1+aY)... chains to
-- returns_oos for runs whose OOS window is covered (validated per strategy).
-- Years outside the OOS window (IS years) are set to NULL (req 3).
-- Every column change is logged to gold.strategy_backtest_runs_annual_pnl_audit
-- (phase='update', task_id='t_fcfe5f4f'). Also gates the 8 strategies out of
-- the trades-sum source in refresh_annual_backtest_returns.py via
-- gold.strategy_configs trades_sum_is_book_annual_return=false.
--
-- Validation summary (chain vs stored returns_oos):
--   etf_trend_overlay_mom12m_v1: canonical audited curve (audit 2026-09-18
--     byte-for-byte vs results JSON); OOS 2022-06..2026-08 (cols cover 2024+)
--   ETF_Global_Risk_Parity_VolTarget: rebuilt curve (t_fcfe5f4f), total
--     0.197719==stored 0.1977, sharpe/mdd/win/108 legs exact
--   ETF_Multi_Asset_Tactical_Allocation: canonical oos_lot metrics JSON
--     2026-07-29; 1.0846*1.2640*1.1324=1.5525==returns_oos 0.5525
--   etf_vix_scaled_11: qa_reproduce results JSON; 1.2222*1.1092=1.3557==0.3557
--   HK_LowVol_TrendFilter_Weekly: root trade log PV-ratio;
--     1.1696*1.0282=1.2026==0.2026
--   hk_ipo_postlisting_drift_c1: hk_ipo_batch C1 log;
--     1.1964*1.4747*1.2373=2.1831==1.1830
--   ETF_US_Sector_Relative_Momentum: tuned (top4/22.5%) engine re-run,
--     mdd -0.06765==-0.0676; 1.1237*1.2301=1.3823==0.3823
--   COMM_Gold_Trend_VolTarget: latest run = postbackfill lb126_vt15;
--     1.5633*(1-0.0985)=1.4093==0.4093

BEGIN;

-- 0) gate the trades-sum source OFF for the 8 (idempotent)
INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value, description)
SELECT s, 'trades_sum_is_book_annual_return', 'false'::jsonb,
       'Book-level annuals owned by correction pipeline (t_fcfe5f4f): SUM(pnl_pct) of legs/trades is not a book annual return (multi-leg books, incomplete ledgers). annual_pnl_YYYY corrected from canonical equity curves 2026-09-21.'
FROM (VALUES
  ('etf_trend_overlay_mom12m_v1'),
  ('ETF_Global_Risk_Parity_VolTarget'),
  ('ETF_Multi_Asset_Tactical_Allocation'),
  ('etf_vix_scaled_11'),
  ('HK_LowVol_TrendFilter_Weekly'),
  ('hk_ipo_postlisting_drift_c1'),
  ('ETF_US_Sector_Relative_Momentum'),
  ('COMM_Gold_Trend_VolTarget')
) AS v(s)
WHERE NOT EXISTS (
  SELECT 1 FROM gold.strategy_configs c
  WHERE c.strategy_id = v.s AND c.config_key = 'trades_sum_is_book_annual_return'
);

-- 1) correction table driver: strategy, annuals, source note
CREATE TEMP TABLE _fix (
  strategy_id text PRIMARY KEY,
  a2024 numeric, a2025 numeric, a2026 numeric, src text
) ON COMMIT DROP;
INSERT INTO _fix VALUES
  ('etf_trend_overlay_mom12m_v1',            0.1625,  0.2504,  0.0640, 'canonical audited daily curve etf_trend_overlay_mom12m_v1_trade_log.csv (audit 2026-09-18)'),
  ('ETF_Global_Risk_Parity_VolTarget',       NULL,    0.1318,  0.0582, 'rebuilt curve per deployed spec (t_fcfe5f4f); total/sharpe/mdd/win/legs exact vs run'),
  ('ETF_Multi_Asset_Tactical_Allocation',    0.0846,  0.2640,  0.1324, 'canonical oos_lot metrics multi_asset_lot_aware_metrics_2026-07-29.json'),
  ('etf_vix_scaled_11',                      NULL,    0.2222,  0.1092, 'qa_reproduce results expansion_2026-08-06/audit_vix_d1.5_g0.3'),
  ('HK_LowVol_TrendFilter_Weekly',           NULL,    0.1696,  0.0282, 'PV-ratio chained annuals from HK_LowVol_TrendFilter_Weekly_trade_log.csv'),
  ('hk_ipo_postlisting_drift_c1',            0.1964,  0.4747,  0.2373, 'hk_ipo_batch/ipo_pulse_C1_trade_log.csv (2026-09-17 run)'),
  ('ETF_US_Sector_Relative_Momentum',        NULL,    0.1237,  0.2301, 'tuned top4/22.5% engine re-run (t_fcfe5f4f), data<=2026-09-17'),
  ('COMM_Gold_Trend_VolTarget',              NULL,    0.5633, -0.0985, 'postbackfill lb126_vt15 trade log (= latest run 545f6983)');

-- 2) audit rows (old vs new per column) for the latest run per strategy
INSERT INTO gold.strategy_backtest_runs_annual_pnl_audit
  (phase, task_id, strategy_id, run_id, annual_pnl_2024, annual_pnl_2025, annual_pnl_2026,
   returns_oos, column_name, old_value, new_value, trades_sum_is_book_annual_return)
SELECT 'update', 't_fcfe5f4f', r.strategy_id, r.run_id, f.a2024, f.a2025, f.a2026,
       r.returns_oos, x.col, x.old_v, x.new_v, false
FROM _fix f
JOIN LATERAL (
  SELECT * FROM gold.strategy_backtest_runs b
  WHERE b.strategy_id = f.strategy_id ORDER BY b.created_at DESC LIMIT 1
) r ON true
CROSS JOIN LATERAL (VALUES
  ('annual_pnl_2024', r.annual_pnl_2024, f.a2024),
  ('annual_pnl_2025', r.annual_pnl_2025, f.a2025),
  ('annual_pnl_2026', r.annual_pnl_2026, f.a2026)
) AS x(col, old_v, new_v)
WHERE x.old_v IS DISTINCT FROM x.new_v;

-- 3) apply correction to latest run per strategy
UPDATE gold.strategy_backtest_runs b
SET annual_pnl_2024 = f.a2024,
    annual_pnl_2025 = f.a2025,
    annual_pnl_2026 = f.a2026,
    notes = COALESCE(b.notes, '') || ' | annual_pnl corrected from book-level equity curve (' || f.src || '), t_fcfe5f4f 2026-09-21'
FROM _fix f
WHERE b.strategy_id = f.strategy_id
  AND b.run_id = (
    SELECT run_id FROM gold.strategy_backtest_runs x
    WHERE x.strategy_id = f.strategy_id ORDER BY x.created_at DESC LIMIT 1
  );

-- 4) secondary (a): COMM_Gold_Trend_VolTarget — honest gate flag on the FAIL row
-- (latest run 545f6983 = lb126_vt15 variant grid row, gates: FAIL mdd>=-15%)
UPDATE gold.strategy_backtest_runs
SET all_risk_gates_passed = false,
    notes = COALESCE(notes, '') || ' | all_risk_gates_passed=false set honestly per notes gates: FAIL: mdd>=-15% (t_fcfe5f4f); row is non-deployed variant lb126_vt15 — deployed variant is lb63_vt10 (run 744bb1b5, re-approved t_d9a509e6)'
WHERE run_id = '545f6983-ae78-40e8-bf51-aa7595d5dc7e'
  AND all_risk_gates_passed IS DISTINCT FROM false;

-- 4b) registry metric cleanup for COMM_Gold_Trend_VolTarget: align to DEPLOYED
-- variant lb63_vt10 post-backfill run 744bb1b5 (was mixed: sharpe/mdd from
-- lb63_vt15, returns from lb63_vt10 — flagged in strategy_review_2026-09-18)
UPDATE gold.strategy_registry reg
SET sharpe_oos = src.sharpe_oos,
    returns_oos = src.returns_oos,
    max_drawdown_oos = ABS(src.max_drawdown_oos),
    win_rate_oos = src.win_rate_oos,
    trade_count_oos = src.trade_count_oos,
    profit_factor_oos = src.profit_factor_oos
FROM (
  SELECT sharpe_oos, returns_oos, max_drawdown_oos, win_rate_oos, trade_count_oos, profit_factor_oos
  FROM gold.strategy_backtest_runs WHERE run_id = '744bb1b5-0a4f-47d7-b7fe-2b8a630ca0e2'
) src
WHERE reg.strategy_id = 'COMM_Gold_Trend_VolTarget';

-- 5) secondary (b): crisis_safe_haven_vt_19 — align registry mode with reality
-- (paper monitoring off, v_pipeline_ui_feed reports SIMULATION/experimental)
UPDATE gold.strategy_registry
SET execution_mode = 'SIMULATION'
WHERE strategy_id = 'crisis_safe_haven_vt_19'
  AND execution_mode IS DISTINCT FROM 'SIMULATION';

-- 6) secondary (c): hk_stk_52wh_mom_04 — refresh stale registry metrics from
-- latest run (2026-09-18 R3 re-baseline: returns_oos 0.658 -> 0.8158)
UPDATE gold.strategy_registry reg
SET returns_oos = src.returns_oos,
    sharpe_oos = src.sharpe_oos,
    max_drawdown_oos = ABS(src.max_drawdown_oos),
    win_rate_oos = src.win_rate_oos,
    trade_count_oos = src.trade_count_oos,
    profit_factor_oos = src.profit_factor_oos
FROM (
  SELECT sharpe_oos, returns_oos, max_drawdown_oos, win_rate_oos, trade_count_oos, profit_factor_oos
  FROM gold.strategy_backtest_runs
  WHERE strategy_id = 'hk_stk_52wh_mom_04' ORDER BY created_at DESC LIMIT 1
) src
WHERE reg.strategy_id = 'hk_stk_52wh_mom_04';

COMMIT;
