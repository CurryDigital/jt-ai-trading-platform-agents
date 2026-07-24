-- ============================================================
-- Migration 010 — Declare ONE signal mechanism per strategy (ROADMAP G2,
-- PIPELINE_DESIGN principle 2).
--
-- Today a strategy's BUY can come from several places at once — DB criteria
-- (build_strategy_scores), a dedicated calculator (s9_macd_daily,
-- calc_etf_relative_momentum, the ETF paper runners), or an ingested research
-- file — and ~2/3 of strategies have NO working mechanism and silently show
-- all-HOLD with nobody able to tell "quiet" from "broken".
--
-- This makes the mechanism an explicit, single, queryable fact:
--   gold.strategy_registry.signal_mechanism ∈ {criteria, computed, ingested, none}
-- and surfaces the two failure modes the old sprawl hid:
--   * a strategy with ZERO mechanisms (none)  -> it can never produce a signal
--   * a strategy with MORE THAN ONE           -> two writers can disagree (S9 is
--     both criteria AND s9_macd_daily — pick one).
--
-- Backfill is EVIDENCE-BASED and only auto-sets the UNAMBIGUOUS single-mechanism
-- strategies. Ambiguous (multi) and empty (none) are left for the operator to
-- resolve using gold.v_strategy_mechanism_audit below — the migration does not
-- silently pick a winner.
--
-- Idempotent. Safe to re-run.
-- ============================================================

SET search_path = gold, public;
SET client_min_messages = WARNING;

ALTER TABLE gold.strategy_registry
    ADD COLUMN IF NOT EXISTS signal_mechanism VARCHAR(12);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='strategy_registry_signal_mechanism_chk') THEN
        ALTER TABLE gold.strategy_registry
            ADD CONSTRAINT strategy_registry_signal_mechanism_chk
            CHECK (signal_mechanism IS NULL OR signal_mechanism IN ('criteria','computed','ingested','none'));
    END IF;
END $$;

-- Strategies whose BUY logic lives in a dedicated CALCULATOR (code, not data).
-- This is the one place that list is written down; keep it in sync with the
-- scripts under agents/signals/pipeline + agents/etl/gold/strategy.
CREATE TEMP TABLE _computed(strategy_id text) ON COMMIT DROP;
INSERT INTO _computed VALUES
    ('S9_MACD_Momentum_V2'),
    ('ETF_US_Sector_Relative_Momentum'),
    ('ETF_Multi_Asset_Tactical_Allocation'),
    ('ETF_Covered_Call_Income_Rotation');

-- Per-strategy evidence + a health verdict.
CREATE OR REPLACE VIEW gold.v_strategy_mechanism_audit AS
WITH ev AS (
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
    CASE
        WHEN (has_criteria::int + has_signal_file::int + is_computed::int) = 0 THEN 'none'
        WHEN (has_criteria::int + has_signal_file::int + is_computed::int) > 1 THEN 'multiple'
        ELSE 'ok'
    END AS verdict
FROM ev;

GRANT SELECT ON gold.v_strategy_mechanism_audit TO openclaw_user;

-- Auto-set ONLY the unambiguous single-mechanism strategies.
UPDATE gold.strategy_registry r
SET signal_mechanism = a.mech
FROM (
    SELECT strategy_id,
           CASE WHEN has_criteria THEN 'criteria'
                WHEN is_computed  THEN 'computed'
                WHEN has_signal_file THEN 'ingested' END AS mech
    FROM gold.v_strategy_mechanism_audit
    WHERE verdict = 'ok'
) a
WHERE r.strategy_id = a.strategy_id
  AND r.signal_mechanism IS DISTINCT FROM a.mech;

-- Strategies with zero mechanisms are honestly 'none' (they produce no signal).
UPDATE gold.strategy_registry r
SET signal_mechanism = 'none'
FROM gold.v_strategy_mechanism_audit a
WHERE r.strategy_id = a.strategy_id AND a.verdict = 'none'
  AND r.signal_mechanism IS NULL;

-- 'multiple' left as NULL on purpose — operator resolves (drop criteria or the
-- calculator) then sets signal_mechanism explicitly.

DO $$
DECLARE n_ok INT; n_none INT; n_multi INT;
BEGIN
    SELECT COUNT(*) FILTER (WHERE verdict='ok'),
           COUNT(*) FILTER (WHERE verdict='none'),
           COUNT(*) FILTER (WHERE verdict='multiple')
      INTO n_ok, n_none, n_multi FROM gold.v_strategy_mechanism_audit;
    RAISE NOTICE 'Migration 010: signal_mechanism set. ok=% none=% multiple=%', n_ok, n_none, n_multi;
    RAISE NOTICE '  none  = no working signal path (all-HOLD forever) — wire a mechanism.';
    RAISE NOTICE '  multiple = two writers may disagree (e.g. S9 criteria + s9_macd_daily) — pick one.';
    RAISE NOTICE '  Inspect: SELECT * FROM gold.v_strategy_mechanism_audit WHERE verdict <> ''ok'';';
END $$;
