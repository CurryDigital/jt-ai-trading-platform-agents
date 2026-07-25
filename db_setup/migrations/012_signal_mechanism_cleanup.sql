-- ============================================================
-- Migration 012 — Finish the G2 cleanup: clear the stale signal_file_paths the
-- evidence_conflict flag surfaced, and honestly resolve the verdict='none'
-- strategies by evidence (retire the truly-inert orphans; leave the rest, which
-- have a universe/backtest and so represent real but unwired intent, as 'none'
-- for onboarding — ROADMAP G6).
--
-- Two threads, both evidence-based, both reversible:
--
-- (1) evidence_conflict cleanup. ETF_US_Sector_Relative_Momentum and
--     ETF_Covered_Call_Income_Rotation are declared 'computed' (a dedicated
--     calculator writes their strategy_ticker_scores), but each still carries a
--     signal_file_path from an earlier ingest-based onboarding. That path is
--     read by NO live pipeline code (only quarantined one-off ingest scripts and
--     the doc/lint tools reference the column), so it is stale provenance that
--     falsely reads as a second 'ingested' mechanism. Clear it. (Multi_Asset
--     KEEPS its path — it is genuinely 'ingested'.)
--
-- (2) verdict='none' resolution, decided by footprint rather than by hand:
--     * The 3 COMM_* rows have ZERO code references anywhere in the repo and
--       (OPERATOR_NOTES flag 5) carry orphan stats written outside the sync with
--       no backtest_runs — dead rows.
--     * earnings_vol_crush_carry + the 3 US_STK_* appear in the remediation /
--       oos-backfill scripts (real intent), they just have no signal wired yet.
--     So auto-retire ONLY a 'none' strategy with a genuinely empty footprint —
--     no universe, no backtest run, no ticker scores — evaluated in SQL so the
--     DB picks, not a hardcoded list. Everything with any footprint is left
--     'none' and flagged for wiring. Reversible: NULL retired_at to restore.
--
-- Idempotent. Safe to re-run (retired rows drop out of the audit view, and the
-- signal_file_path UPDATEs are guarded by IS DISTINCT FROM).
-- ============================================================

SET search_path = gold, public;
SET client_min_messages = WARNING;

-- (1) Clear the stale signal_file_path on the two computed ETFs.
UPDATE gold.strategy_registry
SET signal_file_path = NULL
WHERE strategy_id IN ('ETF_US_Sector_Relative_Momentum', 'ETF_Covered_Call_Income_Rotation')
  AND signal_file_path IS NOT NULL;

-- (2a) Extend the audit view with footprint evidence (has_universe, has_backtest)
--      so 'none' strategies can be told apart: inert orphan vs unwired-but-real.
-- DROP + CREATE, not CREATE OR REPLACE: this inserts has_universe/has_backtest
-- into the middle of the view's shape (via ev.*), which REPLACE cannot do.
-- Nothing depends on this view.
DROP VIEW IF EXISTS gold.v_strategy_mechanism_audit;
CREATE VIEW gold.v_strategy_mechanism_audit AS
WITH _computed(strategy_id) AS (
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
        EXISTS (SELECT 1 FROM _computed cc WHERE cc.strategy_id = r.strategy_id)                    AS is_computed,
        -- COALESCE, not `array_length > 0`: array_length('{}',1) is NULL (not 0),
        -- which would make has_universe NULL and silently break `NOT has_universe`
        -- in the retire gate below (NULL is not TRUE -> orphan never retired).
        (COALESCE(array_length(r.universe_tickers, 1), 0) > 0)                                     AS has_universe,
        EXISTS (SELECT 1 FROM gold.strategy_backtest_runs b WHERE b.strategy_id = r.strategy_id)    AS has_backtest
    FROM gold.strategy_registry r
    WHERE r.retired_at IS NULL
)
SELECT
    ev.*,
    (has_criteria::int + has_signal_file::int + is_computed::int) AS n_mechanisms,
    (declared IS NOT NULL AND declared <> 'none'
        AND (has_criteria::int + has_signal_file::int + is_computed::int) > 1) AS evidence_conflict,
    CASE
        WHEN declared = 'none'      THEN 'none'
        WHEN declared IS NOT NULL   THEN 'ok'
        WHEN (has_criteria::int + has_signal_file::int + is_computed::int) = 0 THEN 'none'
        WHEN (has_criteria::int + has_signal_file::int + is_computed::int) > 1 THEN 'multiple'
        ELSE 'ok'
    END AS verdict
FROM ev;

GRANT SELECT ON gold.v_strategy_mechanism_audit TO openclaw_user;

-- (2b) Auto-retire ONLY the zero-footprint 'none' orphans (the DB decides which).
UPDATE gold.strategy_registry r
SET retired_at = NOW(),
    retirement_reason = 'G2/012 auto-retire: no signal mechanism and empty footprint '
                        '(no universe, no backtest run, no ticker scores). Orphan row. '
                        'Reversible: SET retired_at=NULL, retirement_reason=NULL to restore.'
FROM gold.v_strategy_mechanism_audit a
WHERE r.strategy_id = a.strategy_id
  AND a.verdict = 'none'
  AND NOT a.has_universe
  AND NOT a.has_backtest
  AND r.retired_at IS NULL
  AND NOT EXISTS (SELECT 1 FROM gold.strategy_ticker_scores s WHERE s.strategy_id = r.strategy_id);

DO $$
DECLARE n_retired INT; n_none_left INT; n_conflict INT;
BEGIN
    SELECT COUNT(*) INTO n_retired FROM gold.strategy_registry
        WHERE retirement_reason LIKE 'G2/012 auto-retire%' AND retired_at IS NOT NULL;
    SELECT COUNT(*) FILTER (WHERE verdict='none'),
           COUNT(*) FILTER (WHERE evidence_conflict)
      INTO n_none_left, n_conflict FROM gold.v_strategy_mechanism_audit;
    RAISE NOTICE 'Migration 012: signal_file_path cleared on the 2 computed ETFs.';
    RAISE NOTICE '  auto-retired % zero-footprint orphan(s):', n_retired;
    RAISE NOTICE '    SELECT strategy_id, retirement_reason FROM gold.strategy_registry WHERE retirement_reason LIKE ''G2/012%%'';';
    RAISE NOTICE '  evidence_conflict now = % (expect 0).', n_conflict;
    RAISE NOTICE '  verdict=none remaining = % — real but UNWIRED (have a universe/backtest); wire or retire (G6):', n_none_left;
    RAISE NOTICE '    SELECT strategy_id, has_universe, has_backtest FROM gold.v_strategy_mechanism_audit WHERE verdict=''none'';';
END $$;
