-- 2026-10-28_paper_trade_cost_model.sql (kanban t_f81b2bb2)
--
-- FIX_EXECUTION: paper ledger must charge the declared cost model.
-- gold.paper_trades_synthetic recorded entry/exit at raw prices with pnl
-- gross of ALL costs, while the approved sims charge per-strategy declared
-- bps (batch10 SPECS 5bps US / 15bps HK, batch11 5bps US / 15bps CN-SG,
-- multi_asset rebacktest 10bps/turnover, expansion-v2 5bps/turnover, etc).
-- Every paper-vs-sim comparison was invalid (paper gross, sim net).
--
-- This migration:
--   1. adds explicit cost columns to the ledger (append-only: entry/exit
--      prices are NEVER rewritten);
--   2. seeds gold.strategy_configs config_key='cost_bps' with the DECLARED
--      per-strategy cost model mined from the approved handoff manifests and
--      backtest engines (qr_research workspace, 2026-10-28 audit).
--
-- Value shape (jsonb):
--   {"default": <bps per leg>, "markets": {"US": 5, "HK": 15, ...},
--    "declared": true, "provenance": "<source>"}
-- Resolution: markets[asset_registry.market] when present, else default.
-- "declared": false would mean ETL-assumed (none here — every row below is
-- backed by a cited source; gross models are declared 0, not missing).

ALTER TABLE gold.paper_trades_synthetic
  ADD COLUMN IF NOT EXISTS entry_cost NUMERIC,
  ADD COLUMN IF NOT EXISTS exit_cost NUMERIC,
  ADD COLUMN IF NOT EXISTS cost_bps_applied NUMERIC;

COMMENT ON COLUMN gold.paper_trades_synthetic.entry_cost IS
  'Transaction cost charged on the entry leg: entry_price*n_shares*cost_bps_applied/1e4 (t_f81b2bb2).';
COMMENT ON COLUMN gold.paper_trades_synthetic.exit_cost IS
  'Transaction cost charged on the exit leg: exit_price*n_shares*cost_bps_applied/1e4 (t_f81b2bb2).';
COMMENT ON COLUMN gold.paper_trades_synthetic.cost_bps_applied IS
  'Declared cost bps per leg resolved from gold.strategy_configs cost_bps at write time (t_f81b2bb2). pnl = (exit-entry)*n_shares - entry_cost - exit_cost.';

INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value, description, updated_at)
VALUES
  -- batch10 SPECS 2026-08-05: 5bps US / 15bps HK
  ('us_stk_sue_mom_01_v2', 'cost_bps', '{"default": 5, "markets": {"US": 5, "HK": 15}, "declared": true, "provenance": "batch10 SPECS (strategy_handoff_manifest_20260805.json): costs 5bps US / 15bps HK"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('hk_stk_52wh_mom_04', 'cost_bps', '{"default": 15, "markets": {"US": 5, "HK": 15}, "declared": true, "provenance": "batch10 SPECS (strategy_handoff_manifest_20260805.json): costs 5bps US / 15bps HK"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('etf_tsmom_basket_07', 'cost_bps', '{"default": 5, "markets": {"US": 5, "HK": 15}, "declared": true, "provenance": "batch10 SPECS (strategy_handoff_manifest_20260805.json): costs 5bps US / 15bps HK"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('etf_country_rot_10_v2', 'cost_bps', '{"default": 5, "markets": {"US": 5, "HK": 15}, "declared": true, "provenance": "batch10 SPECS (strategy_handoff_manifest_20260805.json): costs 5bps US / 15bps HK"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- batch11 SPECS 2026-08-05: 5bps US / 15bps CN-SG
  ('cn_stk_lowvol_12', 'cost_bps', '{"default": 15, "markets": {"US": 5, "CN": 15, "SG": 15}, "declared": true, "provenance": "batch11 SPECS (strategy_handoff_manifest_20260805_batch11.json): costs 5bps US / 15bps CN-SG"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('sg_stk_52wh_mom_13', 'cost_bps', '{"default": 15, "markets": {"US": 5, "CN": 15, "SG": 15}, "declared": true, "provenance": "batch11 SPECS (strategy_handoff_manifest_20260805_batch11.json): costs 5bps US / 15bps CN-SG"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('us_stk_lowbeta_14', 'cost_bps', '{"default": 5, "markets": {"US": 5, "CN": 15, "SG": 15}, "declared": true, "provenance": "batch11 SPECS (strategy_handoff_manifest_20260805_batch11.json): costs 5bps US / 15bps CN-SG"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('etf_vix_scaled_11', 'cost_bps', '{"default": 5, "markets": {"US": 5, "CN": 15, "SG": 15}, "declared": true, "provenance": "batch11 SPECS (strategy_handoff_manifest_20260805_batch11.json): costs 5bps US / 15bps CN-SG"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('etf_tech_mom_13', 'cost_bps', '{"default": 5, "markets": {"US": 5, "CN": 15, "SG": 15}, "declared": true, "provenance": "batch11 SPECS (strategy_handoff_manifest_20260805_batch11.json): costs 5bps US / 15bps CN-SG"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('etf_def_sector_rot_12_w', 'cost_bps', '{"default": 5, "markets": {"US": 5, "CN": 15, "SG": 15}, "declared": true, "provenance": "batch11 SPECS (strategy_handoff_manifest_20260805_batch11.json): costs 5bps US / 15bps CN-SG"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- batch12 SPECS 2026-08-05: 5bps
  ('etf_comm_trend_basket_15', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "batch12 SPECS (strategy_handoff_manifest_20260805_batch12.json): 5bps costs"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- batch13 2026-08-06: 5bps
  ('crisis_safe_haven_vt_19', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "batch13 audit_safe_haven batch13_backtest.py: costs 5bps"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- multi_asset rebacktest 2026-07-29: 10bps per unit turnover
  ('ETF_Multi_Asset_Tactical_Allocation', 'cost_bps', '{"default": 10, "markets": {}, "declared": true, "provenance": "multi_asset_10asset_rebacktest_2026-07-29.py COST_BPS=0.0010 (10bps/turnover; manifest strategy_handoff_manifest_2026-07-29_multi_asset_10asset.json)"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- expansion v2 2026-07-30: TX_COST=5bps per unit turnover (all strategies in that engine)
  ('US_STK_LOWVOL_DIV_02', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('US_STK_QUAL_ROE_07', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('US_STK_MOM_LDR_01', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005 (SPECS row cost=5)"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('US_STK_DEF_MOM_10', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005 (SPECS row cost=5)"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('US_STK_SM_CAP_CRED_08', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005 (SPECS row cost=5)"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('US_STK_GOLD_HDG_05', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005 (specs_etf)"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('ETF_HK_Balanced_Trend', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('ETF_Small_Cap_Momentum', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('ETF_Defensive_Equity_Income', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('ETF_REIT_Dividend_Momentum', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('ETF_Dividend_Aristocrats_Treasury_Barbell', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('ETF_HY_Credit_Carry', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "expansion_2026-07-30/universe_expansion_v2_backtest.py TX_COST=0.0005; manifest 20260730 notes: honest metrics 5bps cost"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- HK IPO batch: 15bps each way
  ('hk_ipo_postlisting_drift_p1', 'cost_bps', '{"default": 15, "markets": {}, "declared": true, "provenance": "strategy_handoff_manifest_20260831.json: Costs 15bps each way assumed"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('hk_ipo_postlisting_drift_p1_v3', 'cost_bps', '{"default": 15, "markets": {}, "declared": true, "provenance": "hk_ipo_batch ipo_pulse_v3.py: 15bps cost each way"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('hk_ipo_postlisting_drift_c1', 'cost_bps', '{"default": 15, "markets": {}, "declared": true, "provenance": "hk_ipo_batch audit_c1 ipo_pulse_c1.py: 15bps cost each way"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- HK Quality BlueChips: COST_BPS=0.002 applied as fraction per leg
  ('HK_Quality_BlueChips', 'cost_bps', '{"default": 20, "markets": {}, "declared": true, "provenance": "hk_quality_bluechips_retest_v3.py COST_BPS=0.002 applied to proceeds and buys (20bps per leg)"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- S9 MACD: 5bps per side
  ('S9_MACD_Momentum_V2', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "daytrade_research artifact_S9_MACD_Momentum_V2.json: 5bps per side (entry + exit)"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- VIX spike event: 5bps per side per leg
  ('us_vix_spike_crisis_event_v3', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "vix_spike_event_batch signals.json: costs 5bps per side per leg"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- gapdaily 2026-08-18: 5bps/unit one-way turnover (futures)
  ('COMM_Gold_Trend_VolTarget', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "gapdaily_2026-08-18/gapdaily_backtest.py variant registry: GC=F cost=5bps one-way"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  ('COMM_Copper_Trend_VolTarget', 'cost_bps', '{"default": 5, "markets": {}, "declared": true, "provenance": "gapdaily_2026-08-18/gapdaily_backtest.py variant registry: HG=F cost=5bps one-way"}', 'Declared cost model (t_f81b2bb2)', NOW()),
  -- Declared GROSS models (approved backtests charged no transaction costs):
  ('COMM_GoldSilver_Ratio_MeanRev_VolTarget', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "bt_gs_ratio_voltarget.py: no transaction costs (monthly frequency)"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW()),
  ('ETF_Covered_Call_Income_Rotation', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "etf_backtest_remediation.py backtest(transaction_cost=0.000 default); 2026-07-17 approved batch, no cost line"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW()),
  ('ETF_Global_Risk_Parity_VolTarget', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "etf_backtest_remediation.py backtest(transaction_cost=0.000 default); 2026-07-17 approved batch, no cost line"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW()),
  ('ETF_US_Sector_Relative_Momentum', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "ETF_US_Sector_Relative_Momentum_corrected_backtest.py has no transaction-cost line; approved metrics gross"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW()),
  ('HK_LowVol_Weekly', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "build_hk_manifest.py: weekly rebalance may incur transaction costs not modeled in the backtest"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW()),
  ('HK_LowVol_TrendFilter_Weekly', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "build_hk_manifest.py: weekly rebalance may incur transaction costs not modeled in the backtest"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW()),
  ('gc_cot_contrarian_inverse', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "backtest_cot_per_instrument.py has no transaction-cost line; approved metrics gross"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW()),
  ('etf_trend_overlay_mom12m_v1', 'cost_bps', '{"default": 0, "markets": {}, "declared": true, "provenance": "trend_overlay_backtest.py has no transaction-cost line; approved metrics gross"}', 'Declared cost model: GROSS (t_f81b2bb2)', NOW())
ON CONFLICT (strategy_id, config_key) DO NOTHING;
