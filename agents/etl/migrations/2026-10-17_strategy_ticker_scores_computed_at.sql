-- strategy_ticker_scores.computed_at: the strategy's OWN signal-compute time
-- (from the live-signals file's generated_at at ingest). updated_at stays the
-- ETL write stamp. Freshness checks (deadman SIGNAL STALE, rebalance gate
-- poll) read COALESCE(computed_at, updated_at) — user directive 2026-10-17.
ALTER TABLE gold.strategy_ticker_scores
    ADD COLUMN IF NOT EXISTS computed_at timestamptz;

-- Backfill from criteria_met->>'generated_at' (set by ingest_paper_signal.py).
UPDATE gold.strategy_ticker_scores
SET computed_at = NULLIF(criteria_met->>'generated_at', '')::timestamptz
WHERE computed_at IS NULL
  AND criteria_met ? 'generated_at'
  AND NULLIF(criteria_met->>'generated_at', '') IS NOT NULL;
