-- ============================================================
-- Migration 005 — Append-only signal history (OPERATOR_NOTES.md P0-3).
--
-- gold.strategy_ticker_scores is a single-row-per-(strategy, ticker) upsert:
-- every signal cycle overwrites the previous score, so the system keeps NO
-- record of what its signal was yesterday. That makes honest signal-quality
-- measurement (hit rate, forward returns) impossible by construction — the
-- exact vacuum that fabricated performance numbers were once invented to
-- fill. This table is the fix: one snapshot row per (strategy, ticker,
-- snapshot day), written at the END of each signal cycle so it captures the
-- final state from ALL score writers (criteria scorer, S9, paper-signal
-- ingesters), not just one.
--
-- Same-day re-runs UPDATE the day's row (last write wins for the day);
-- prior days are never touched — append-only by date.
--
-- Populated by: agents/signals/pipeline/snapshot_ticker_scores.py
--               (run_signal_cycle.sh, final pipeline step)
--
-- Idempotent: CREATE TABLE IF NOT EXISTS. Safe to re-run.
-- ============================================================

SET search_path = gold, public;
SET client_min_messages = WARNING;

CREATE TABLE IF NOT EXISTS gold.strategy_ticker_scores_history (
    snapshot_date   DATE         NOT NULL,
    strategy_id     VARCHAR(50)  NOT NULL,
    ticker          VARCHAR(20)  NOT NULL,
    score           NUMERIC(5,2),
    signal_action   VARCHAR(10),
    entry_score     NUMERIC(5,2),
    exit_score      NUMERIC(5,2),
    criteria_met    JSONB        DEFAULT '{}'::jsonb,
    position_status VARCHAR(20)  DEFAULT 'NONE',
    snapshotted_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
    PRIMARY KEY (snapshot_date, strategy_id, ticker),
    CONSTRAINT sts_history_score_check
        CHECK (score IS NULL OR (score >= 0 AND score <= 100)),
    CONSTRAINT sts_history_signal_action_check
        CHECK (signal_action IS NULL OR signal_action IN ('BUY','SELL','HOLD'))
);

CREATE INDEX IF NOT EXISTS sts_history_strategy_date_idx
    ON gold.strategy_ticker_scores_history (strategy_id, snapshot_date DESC);
CREATE INDEX IF NOT EXISTS sts_history_ticker_date_idx
    ON gold.strategy_ticker_scores_history (ticker, snapshot_date DESC);

ALTER TABLE gold.strategy_ticker_scores_history OWNER TO openclaw_user;
GRANT SELECT, INSERT, UPDATE ON gold.strategy_ticker_scores_history TO openclaw_user;

DO $$
DECLARE
    n_rows INTEGER;
BEGIN
    SELECT COUNT(*) INTO n_rows FROM gold.strategy_ticker_scores_history;
    RAISE NOTICE 'Migration 005 complete: strategy_ticker_scores_history ready (% rows)', n_rows;
END $$;
