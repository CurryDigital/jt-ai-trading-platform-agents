# annual_pnl audit snapshot (t_ce0deace)

Rollback + before/after comparison record for the annual_pnl_YYYY correction.

- Origin: t_d152898f — consumption.strategy_monthly_returns was rebuilt from
  verified research portfolio curves; the 30 published strategies' monthly
  heatmap now compounds correctly. But for 21 of those 30 strategies the
  gold.strategy_backtest_runs.annual_pnl_2024/2025/2026 columns still hold
  legacy UNWEIGHTED trades-sum annuals, which feed the Strategy Detail yearly
  bars (backend/app/routes/strategies.py) and no longer compound-match the
  corrected heatmap.
- Correction: t_6ea23eae (decomposed; DB UPDATE step t_86a4a973) replaces the
  legacy trades sums with research book annuals computed from verified curve
  artifacts.

## Artifacts

- `gold.strategy_backtest_runs_annual_pnl_audit` (migration
  `migrations/2026-09-07_strategy_backtest_runs_annual_pnl_audit.sql`)
  - phase='before_snapshot': one row per published strategy, latest run,
    capturing run_id + annual_pnl_2024/2025/2026 + returns_oos +
    trades_sum_is_book_annual_return flag as of capture time. THE rollback
    record.
  - phase='update': per-column change log written by the correction task
    (column_name, old_value, new_value).
- `annual_pnl_audit_2026-09-07_t_ce0deace.csv` — versioned CSV export of the
  same snapshot.
- `snapshot_annual_pnl_audit.py` — capture script; re-runnable (replaces this
  task's prior before_snapshot rows). Run only BEFORE the correction lands;
  after t_86a4a973 runs, re-running would capture corrected values.

## Correction applied (t_86a4a973, 2026-09-07)

- `apply_annual_pnl_correction.py` — applied the verified book annuals from
  `annual_compounds_t_abb57f07.json` (t_abb57f07 curve-compounding artifact,
  verified vs gold.strategy_backtest_monthly_returns within 1e-6) to the
  LATEST run of each of the 27 verified strategies. 27 runs updated, 77
  per-column changes logged as phase='update' (task_id='t_86a4a973').
- Decision: annual_pnl_YYYY for years ABSENT from a strategy's artifact
  (outside the latest run's OOS window) were set to NULL, not left at legacy
  values — no book annual exists for those years and the legacy numbers were
  bogus trades sums (e.g. us_stk_sue_mom_01_v2 annual_pnl_2024 +5.05 -> NULL;
  same for cn_stk_lowvol_12, crisis_safe_haven_vt_19, etf_def_sector_rot_12_w,
  etf_tsmom_basket_07, us_stk_lowbeta_14 2024 columns).
- The 3 keep-legacy strategies (H3_VIX_TAIL_HEDGE_V1, S14_OIL_SQUEEZE_DISC_V1,
  S9_MACD_Momentum_V2) were not touched (verified against the snapshot).
- Script is idempotent: re-run plans 0 changes and appends 0 audit rows.
- `--dry-run` prints the full change plan without writing.

## Flag check

Strategies with gold.strategy_configs trades_sum_is_book_annual_return=false
(book annuals already research-verified, NOT corrected): the 4 hk_ipo books
(hk_ipo_postlisting_drift_p1, _p1_v3, _p2, hk_ipo_day1_green_momentum_v1) +
hk_stk_52wh_mom_04 + sg_stk_52wh_mom_13. All other published strategies
default to true (annuals are legacy trades sums until corrected).

## Rollback

To revert the correction for a strategy, restore annual_pnl_YYYY from the
phase='before_snapshot' row matching that strategy's run_id, and delete the
corresponding phase='update' rows.
