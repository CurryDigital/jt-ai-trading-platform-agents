-- 2026-08-17 (kanban t_ee1ab601): declare per-strategy paper design metadata.
--
-- Problem: the paper rebalancer's concentration cap fell back to a SILENT
-- global default (max_position_pct=0.20) for every strategy without an
-- explicit gold.strategy_configs override. That silently overrode declared
-- strategy designs (e.g. ETF_US_Sector_Relative_Momentum is designed
-- 30/30/30 + 10% residual cash; every leg was capped at 20%, leaving the
-- book 47.3% deployed with ~52% unintended cash, 2026-08-06..08-14).
--
-- Fix: a 'paper_design' config row per active strategy declaring:
--   slot_count              design position slots (drives UI slot display)
--   weighting               design weighting scheme (human-readable)
--   design_max_position_pct cap derived from the declared design; NULL when
--                           an explicit max_position_pct override row already
--                           declares the cap, or when the design has no
--                           per-name constraint (global default then applies
--                           and is LOGGED as a declared fallback, not silent)
--   residual_cash_policy    the engine's declared residual-cash policy
--   design_source           where the design is declared (audit trail)
--
-- rebuild_paper_positions.py precedence after this change:
--   explicit max_position_pct override > paper_design.design_max_position_pct
--   > global default (CLI --max-position-pct), with the source logged.

INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value, description)
VALUES
  ('ETF_US_Sector_Relative_Momentum', 'paper_design', $$
{
  "slot_count": 3,
  "weighting": "equal top-3 (research handoff 30/30/30 + 10% residual cash)",
  "design_max_position_pct": 0.34,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "calc_etf_relative_momentum.py assign_scores docstring (30/30/30 + 10% cash); build_rotation_signals STRATEGY_CONFIGS top_n=3 equal",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Top-3 equal weight 33/33/33 design; 0.34 cap = 1/3 plus whole-lot rounding headroom. Was silently capped at the 20% global default 2026-08-06..08-14 (XLF 500->300, IWM 100->0, XLK residual blocked daily; book 47.3% deployed).'),

  ('etf_tsmom_basket_07', 'paper_design', $$
{
  "slot_count": 10,
  "weighting": "10-asset vol-target TSMOM basket (leverage_cap 1.5; paper engine unlevered)",
  "design_max_position_pct": 0.20,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "gold.strategy_research.position_sizing.max_single_asset_cap_post_leverage = 0.20",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap was previously the SILENT global default; now explicitly declared at the research-specified 0.20 post-leverage single-asset cap. No behavior change; declaration only. NOTE: research position_sizing says residual-to-cash, but the paper engine deploys residual round-robin; engine policy is the operative one for the paper book (flagged for research reconciliation).'),

  ('crisis_safe_haven_vt_19', 'paper_design', $$
{
  "slot_count": 2,
  "weighting": "top-2 60/40 (GLD/TLT/IEF 63d momentum, 252d abs filter); failing leg -> IEF; residual -> IEF",
  "design_max_position_pct": 1.0,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS safe_haven_v2 (risk stage accepted 60% max single-asset > 50% cap as intended design, t_ab33144a); residual->IEF makes a 100% IEF state reachable by design",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'IEF was capped at 20% daily 2026-08-07..08-14 while the design was in its single-name IEF state (score 100). Cap 1.0 declared: the safe-haven design intentionally concentrates into IEF.'),

  ('COMM_GoldSilver_Ratio_MeanRev_VolTarget', 'paper_design', $$
{
  "slot_count": 1,
  "weighting": "single-asset sleeve; exposure = min(1, vol_target / trailing realized vol) of capital",
  "design_max_position_pct": 1.0,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "gold.strategy_research.position_sizing (exposure min(1, vol_target/realized_vol), long_only); build_rotation_signals gs_ratio_meanrev_voltarget",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'GC=F was capped at 20% daily 2026-08-06..08-14 against a design that allows up to 100% single-asset exposure (unlevered). Cap 1.0 declared.'),

  ('ETF_Global_Risk_Parity_VolTarget', 'paper_design', $$
{
  "slot_count": 6,
  "weighting": "inverse-vol risk parity across full 6-asset universe; scores are target portfolio weights (sum = 1.0), 10% vol target, unlevered",
  "design_max_position_pct": 1.0,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS (top_n=all, risk_parity_voltarget); strategy_ticker_scores sum to 1.0 (target portfolio weights); precedent: sibling weight-emitting strategies carry max_position_pct=1.0 overrides",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'AGG/TLT/VNQ capped at 20% daily 2026-08-06..08-14 while inverse-vol design assigns AGG ~43% (low-vol concentration is the design, not a breach). Cap 1.0 declared per weight-emitter precedent.'),

  ('etf_comm_trend_basket_15', 'paper_design', $$
{
  "slot_count": 6,
  "weighting": "inverse-63d-vol TSMOM basket (GLD/SLV/DBC/USO/UNG + IEF all-out fallback); weights are target portfolio",
  "design_max_position_pct": 0.20,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "declared guardrail retained from t_569c181f incident (DBC reached 22.65% via residual round-robin, 2026-08-05); 20% cap is the accepted risk bound for this sleeve",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap 0.20 is a DECLARED incident guardrail (t_569c181f), not a silent default. Residual round-robin may still push a name to the cap; breaches stay logged as CONCENTRATION_CAP.'),

  ('ETF_Multi_Asset_Tactical_Allocation', 'paper_design', $$
{
  "slot_count": 3,
  "weighting": "inverse-vol top-3 of 10-asset universe, cash_if_negative",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS (top_n=3, inverse_vol); cap declared via explicit max_position_pct=0.35 override (risk reviewed)",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap already declared via explicit max_position_pct=0.35 override; EFA CONCENTRATION_CAP skips 2026-08-11..08-14 are the configured guardrail working as risk-reviewed.'),

  ('etf_country_rot_10_v2', 'paper_design', $$
{
  "slot_count": 2,
  "weighting": "top-2 50/50 of 14 country ETFs, 252d abs filter, failing leg -> IEF, lev <= 1.3 (paper unlevered)",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS country_rot_x14; cap declared via explicit max_position_pct=1.0 override",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap already declared via explicit max_position_pct=1.0 override (weights are target portfolio).'),

  ('etf_tech_mom_13', 'paper_design', $$
{
  "slot_count": 2,
  "weighting": "top-2 of SMH/QQQ/XLK/IGV 0.5/0.5, 200d-SMA filter, failing leg -> 50/50 IEF/GLD",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS tech_mom_gld_fallback; cap declared via explicit max_position_pct=1.0 override",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap already declared via explicit max_position_pct=1.0 override.'),

  ('etf_trend_overlay_mom12m_v1', 'paper_design', $$
{
  "slot_count": 4,
  "weighting": "4 legs x 25% (SPY/QQQ/GLD/TLT), leg -> IEF when risk-off, IEF risk-off -> CASH",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "gold.strategy_research.position_sizing (leg_weight 0.25); build_rotation_signals trend_overlay_mom12m; cap declared via explicit max_position_pct=1.0 override",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap already declared via explicit max_position_pct=1.0 override.'),

  ('etf_vix_scaled_11', 'paper_design', $$
{
  "slot_count": 4,
  "weighting": "VIX-scaled equity (SPY 0.6 / QQQ 0.4 of eq) + defensive remainder (IEF 0.7 / GLD 0.3)",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS vix_scaled_gld_sleeve; cap declared via explicit max_position_pct=0.60 override",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap already declared via explicit max_position_pct=0.60 override; SPY/QQQ cap notes 2026-08-06 are the configured guardrail working.'),

  ('etf_def_sector_rot_12_w', 'paper_design', $$
{
  "slot_count": null,
  "weighting": "ingested defensive sector rotation (weekly)",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "ingested signals; cap declared via explicit max_position_pct=1.0 override",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Cap already declared via explicit max_position_pct=1.0 override.'),

  ('HK_LowVol_TrendFilter_Weekly', 'paper_design', $$
{
  "slot_count": 5,
  "weighting": "equal top-5 lowest 63d vol among HK blue-chip universe",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS (top_n=5, equal); global default 0.20 equals the 1/5 design weight (non-binding)",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Design 1/5 = 20% matches the global default; no per-strategy cap needed. Declared fallback.'),

  ('US_STK_VAL_REV_03', 'paper_design', $$
{
  "slot_count": 5,
  "weighting": "equal top-5 by 12w momentum under rates regime filter",
  "design_max_position_pct": null,
  "residual_cash_policy": "freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)",
  "design_source": "build_rotation_signals STRATEGY_CONFIGS (top_n=5, equal); global default 0.20 equals the 1/5 design weight (non-binding)",
  "declared_by": "t_ee1ab601",
  "declared_at": "2026-08-17"
}$$::jsonb,
   'Design 1/5 = 20% matches the global default; no per-strategy cap needed. Declared fallback.')
ON CONFLICT (strategy_id, config_key) DO UPDATE SET
  config_value = EXCLUDED.config_value,
  description  = EXCLUDED.description,
  updated_at   = NOW();

-- Broad-universe ingested / simulation strategies: no per-name design
-- constraint declared. A paper_design row is still written so the absence
-- of a design cap is itself DECLARED (global default applies and is logged),
-- never silent.
INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value, description)
SELECT r.strategy_id, 'paper_design', jsonb_build_object(
    'slot_count', NULL,
    'weighting', 'ingested/broad-universe or simulation sleeve; no per-name design cap declared',
    'design_max_position_pct', NULL,
    'residual_cash_policy', 'freed slot capital redistributed pro-rata by score to fillable BUYs; residual cash deployed round-robin in rank order as whole lots bounded by max_position_pct; remainder parks in cash (compute_target)',
    'design_source', 'no per-strategy design declaration; global default cap applies (declared fallback, logged)',
    'declared_by', 't_ee1ab601',
    'declared_at', '2026-08-17'
  ),
  'Declared fallback: global default max_position_pct applies and is logged with its source.'
FROM gold.strategy_registry r
WHERE r.retired_at IS NULL
  AND r.strategy_id NOT IN (
    'ETF_US_Sector_Relative_Momentum','etf_tsmom_basket_07','crisis_safe_haven_vt_19',
    'COMM_GoldSilver_Ratio_MeanRev_VolTarget','ETF_Global_Risk_Parity_VolTarget',
    'etf_comm_trend_basket_15','ETF_Multi_Asset_Tactical_Allocation',
    'etf_country_rot_10_v2','etf_tech_mom_13','etf_trend_overlay_mom12m_v1',
    'etf_vix_scaled_11','etf_def_sector_rot_12_w','HK_LowVol_TrendFilter_Weekly',
    'US_STK_VAL_REV_03'
  )
ON CONFLICT (strategy_id, config_key) DO UPDATE SET
  config_value = EXCLUDED.config_value,
  description  = EXCLUDED.description,
  updated_at   = NOW();
