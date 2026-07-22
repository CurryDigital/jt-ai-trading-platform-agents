Request to qr_research: HK_Quality_BlueChips calendar-year 2024 annual return
================================================================================

ETL has completed the 2024 backfill for the HK LowVol strategies:

- HK_LowVol_Weekly: 2024 = +8.94%
- HK_LowVol_TrendFilter_Weekly: 2024 = +21.44%

These values were derived by re-running the approved qr_research HK LowVol
backtester (hk_backtest.py) over the IS period (2018-2024). The 2025/2026
outputs of the same re-run exactly match the approved finalized_metrics values
already in ETL, so the 2024 figures are consistent with the approved research.

Remaining gap:
- HK_Quality_BlueChips: 2024 annual return is still missing.

What ETL currently has for HK_Quality_BlueChips:
- DB: annual_pnl_2025 = +29.80%, annual_pnl_2026 = -4.90%
- Approved manifest backtest_results:
  - OOS: 2025-01-01 to 2026-07-17, annual_return = 0.2655
  - IS:  2019-01-01 to 2026-07-17, annual_return = 0.2655
- Approved audit CSV (pipeline_full_audit_2026-07-18.csv):
  - returns_oos = 0.2655, annual_pnl_2025 = 0.298, annual_pnl_2026 = -0.049

Request:
Please provide the calendar-year 2024 annual return (2024-01-01 to 2024-12-31)
for HK_Quality_BlueChips, computed from the same approved backtest
methodology/data that produced the 2025 and 2026 figures above.

Preferred deliverables (any one is fine):
1. A per-year JSON snippet under the HK_Quality_BlueChips entry, e.g.
   {"annual_pnl_2024": 0.XXXX, "annual_pnl_2025": 0.298, "annual_pnl_2026": -0.049}
2. A CSV trade log with exit_date / net_return columns covering 2024.
3. A direct numeric value and the file/command used to compute it.

Once the 2024 value is supplied, ETL will ingest it via
refresh_annual_backtest_returns.py and the dashboard will show the full 3-year
annual returns table for HK_Quality_BlueChips.

— qr_etl, 2026-07-20
