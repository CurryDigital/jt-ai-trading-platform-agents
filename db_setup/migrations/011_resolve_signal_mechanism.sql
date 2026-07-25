-- ============================================================
-- Migration 011 — Resolve the 'multiple' strategies from migration 010 and
-- correct the computed-strategy list (ROADMAP G2 finish).
--
-- Migration 010 flagged 4 strategies as verdict='multiple'. Tracing which script
-- actually writes each strategy's gold.strategy_ticker_scores (the frontend BUY)
-- vs which only simulates paper trades from those scores established the truth:
--
--   S9_MACD_Momentum_V2               -> criteria   (build_strategy_scores from
--       gold.strategy_signal_criteria writes the scores; s9_macd_daily.py writes
--       its OWN gold.s9_macd_signals / gold.s9_paper_trades — an aligned paper
--       tracker, NOT a second writer of strategy_ticker_scores.)
--   ETF_US_Sector_Relative_Momentum   -> computed   (calc_etf_relative_momentum.py)
--   ETF_Covered_Call_Income_Rotation  -> computed   (build_etf_covered_call_paper_signal.sql)
--   ETF_Multi_Asset_Tactical_Allocation -> ingested (ingest_etf_multi_asset_live_signal.py
--       replaces the scores with live research weights; paper_run_etf_multi_asset.py
--       only READS them.)
--
-- So migration 010's hardcoded _computed list was WRONG on two entries: S9 (its
-- frontend signal is criteria, not the calculator) and Multi_Asset (ingested,
-- not computed). This migration corrects that list in the audit view, makes a
-- DECLARED signal_mechanism authoritative in the verdict, and adds
-- evidence_conflict to keep a stale second source visible for later cleanup.
--
-- All three ETFs still carry a stale signal_file_path (provenance from an
-- earlier ingest-based onboarding, read by NO live pipeline code). Rather than
-- destroy that provenance, evidence_conflict flags US_Sector + Covered_Call
-- (declared computed but a stale signal_file remains) so it can be cleared in a
-- reviewed follow-up — not silently here.
--
-- The 7 verdict='none' strategies are left honestly 'none' (no signal path);
-- wiring or retiring them is per-strategy onboarding work (ROADMAP G6), not this.
--
-- Idempotent. Safe to re-run.
-- ============================================================

SET search_path = gold, public;
SET client_min_messages = WARNING;

-- (1) Corrected audit view: accurate _computed list + declaration-authoritative
--     verdict + evidence_conflict advisory.
-- DROP + CREATE, not CREATE OR REPLACE: this adds evidence_conflict BEFORE the
-- existing verdict column, which REPLACE reads as renaming verdict (it can only
-- append at the end). Nothing depends on this view.
DROP VIEW IF EXISTS gold.v_strategy_mechanism_audit;
CREATE VIEW gold.v_strategy_mechanism_audit AS
WITH _computed(strategy_id) AS (
    -- Strategies whose LIVE strategy_ticker_scores are produced by a dedicated
    -- calculator (code/SQL, not criteria rows and not an ingested file).
    VALUES
        ('ETF_US_Sector_Relative_Momentum'),
        ('ETF_Covered_Call_Income_Rotation')
),
ev AS (
    SELECT
        r.strategy_id,
        r.name,
        r.signal_mechanism AS declared,
        EXISTS (SELECT 1 FROM gold.strategy_signal_criteria c WHERE c.strategy_id = r.strategy_id) AS has_criteria,
        (r.signal_file_path IS NOT NULL AND r.signal_file_path <> '')                              AS has_signal_file,
        EXISTS (SELECT 1 FROM _computed cc WHERE cc.strategy_id = r.strategy_id)                    AS is_computed
    FROM gold.strategy_registry r
    WHERE r.retired_at IS NULL
)
SELECT
    ev.*,
    (has_criteria::int + has_signal_file::int + is_computed::int) AS n_mechanisms,
    -- A declared working mechanism that still has >1 evidence source (e.g. a
    -- stale signal_file_path alongside a calculator). Not a failure — a cleanup.
    (declared IS NOT NULL AND declared <> 'none'
        AND (has_criteria::int + has_signal_file::int + is_computed::int) > 1) AS evidence_conflict,
    CASE
        -- The operator's explicit declaration wins over evidence ambiguity...
        WHEN declared = 'none'      THEN 'none'   -- ...except 'none' is honestly broken
        WHEN declared IS NOT NULL   THEN 'ok'
        -- ...falling back to evidence for undeclared strategies.
        WHEN (has_criteria::int + has_signal_file::int + is_computed::int) = 0 THEN 'none'
        WHEN (has_criteria::int + has_signal_file::int + is_computed::int) > 1 THEN 'multiple'
        ELSE 'ok'
    END AS verdict
FROM ev;

GRANT SELECT ON gold.v_strategy_mechanism_audit TO openclaw_user;

-- (2) Declare the 4 formerly-'multiple' strategies (evidence-based, see header).
UPDATE gold.strategy_registry SET signal_mechanism = 'criteria'
    WHERE strategy_id = 'S9_MACD_Momentum_V2'
      AND signal_mechanism IS DISTINCT FROM 'criteria';

UPDATE gold.strategy_registry SET signal_mechanism = 'computed'
    WHERE strategy_id IN ('ETF_US_Sector_Relative_Momentum', 'ETF_Covered_Call_Income_Rotation')
      AND signal_mechanism IS DISTINCT FROM 'computed';

UPDATE gold.strategy_registry SET signal_mechanism = 'ingested'
    WHERE strategy_id = 'ETF_Multi_Asset_Tactical_Allocation'
      AND signal_mechanism IS DISTINCT FROM 'ingested';

DO $$
DECLARE n_ok INT; n_none INT; n_multi INT; n_conflict INT;
BEGIN
    SELECT COUNT(*) FILTER (WHERE verdict='ok'),
           COUNT(*) FILTER (WHERE verdict='none'),
           COUNT(*) FILTER (WHERE verdict='multiple'),
           COUNT(*) FILTER (WHERE evidence_conflict)
      INTO n_ok, n_none, n_multi, n_conflict FROM gold.v_strategy_mechanism_audit;
    RAISE NOTICE 'Migration 011: mechanisms resolved. ok=% none=% multiple=% (evidence_conflict=%)',
        n_ok, n_none, n_multi, n_conflict;
    RAISE NOTICE '  multiple should now be 0 (the 4 are declared criteria/computed/ingested).';
    RAISE NOTICE '  evidence_conflict = declared but a stale second source remains (clear signal_file_path):';
    RAISE NOTICE '    SELECT strategy_id, declared, has_signal_file, is_computed FROM gold.v_strategy_mechanism_audit WHERE evidence_conflict;';
    RAISE NOTICE '  none=% are honestly signal-less — wire or retire (ROADMAP G6):', n_none;
    RAISE NOTICE '    SELECT strategy_id FROM gold.v_strategy_mechanism_audit WHERE verdict=''none'';';
END $$;
