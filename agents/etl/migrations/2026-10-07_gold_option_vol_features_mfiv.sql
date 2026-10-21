-- 2026-10-07_gold_option_vol_features_mfiv.sql
-- Scope: gold.option_vol_features_daily only.
-- Aligns the pre-existing (empty) table with qr_research GOLD_FEATURES_SPEC.md
-- (deriv_equity_enrichment_v1 Task 5): adds the model-free IV column (the spec's
-- rank base + VIX acceptance anchor), rv_30 (21TD close-to-close, annualized),
-- and ops observability columns. Existing columns untouched; spec-deferred
-- columns (skew_25d_30d, iv_term_slope, event_implied_move, iv_pctile_1y,
-- regime, vix_z60) stay NULL — explicitly out of scope per spec.
BEGIN;

ALTER TABLE gold.option_vol_features_daily
    ADD COLUMN IF NOT EXISTS mfiv_30        numeric,  -- model-free 30d constant-maturity IV, vol pts
    ADD COLUMN IF NOT EXISTS rv_30          numeric,  -- std(dlog close, 21TD) * sqrt(252) * 100
    ADD COLUMN IF NOT EXISTS n_strikes_used integer,  -- strikes summed across both bracketing expiries
    ADD COLUMN IF NOT EXISTS quality_flag   text;     -- OK / NO_BRACKET / NO_RATE / NO_GREEKS

COMMENT ON COLUMN gold.option_vol_features_daily.mfiv_30 IS
    'VIX-methodology model-free 30d IV from silver.option_eod_quotes (OTM puts/calls around K0, parity forward). Acceptance anchor: median |mfiv_30(SPY) - VIXCLS| < 1.5 vol pts.';
COMMENT ON COLUMN gold.option_vol_features_daily.atm_iv_30d IS
    'ATM constant-30d IV from silver.option_eod_greeks (COMPUTED), put/call averaged at K0 nearest F, total-variance interpolated. Reporting/strike-selection only; ranking series is mfiv_30.';

COMMIT;
