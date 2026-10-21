-- 019_strategy_rebalance_state.sql
-- t_68b07c59: cadence-gated rebalance execution for the paper engine.
--
-- One row per cadence-gated strategy (frequency weekly/monthly).
-- rebuild_paper_positions.py compares the period key of the run date
-- (W:<iso_year>-<iso_week> or M:<year>-<month>) against last_period_key:
-- a difference means today is a rebalance date; equality means signals
-- only, no position mutations. daily/event strategies are ungated and
-- have no rows here.
--
-- The engine also CREATEs this table IF NOT EXISTS at runtime
-- (self-healing, same pattern as the skip-surface tables); this migration
-- is the canonical DDL of record.

CREATE TABLE IF NOT EXISTS gold.strategy_rebalance_state (
  strategy_id         TEXT PRIMARY KEY,
  frequency           TEXT NOT NULL,
  last_period_key     TEXT NOT NULL,
  last_rebalance_date DATE,
  seeded              BOOLEAN NOT NULL DEFAULT FALSE,
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE gold.strategy_rebalance_state IS
  'Cadence gate state for the paper rebalancer (t_68b07c59). last_period_key is the period of the most recent EXECUTED rebalance; seeded=TRUE rows were initialized at gate rollout without executing a rebalance.';
