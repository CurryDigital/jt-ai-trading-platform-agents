-- 2026-10-26_paper_feeder_append_only.sql
-- Kanban t_47a76ea3 / c1_trust_audit_2026-10-26.md Finding 3.
-- Make the synthetic paper ledger append-only capable:
--   * immutable identity key (strategy_id, ticker, entry_date)
--   * immutable run_id + first_seen_at on every row (entry side never mutated)
--   * exit-side provenance (exit_run_id, exit_updated_at)
--   * gold.paper_feeder_runs audit table (one row per feeder run)
-- Additive only: existing DELETE+re-INSERT writers keep working until converted.

BEGIN;

-- 1. New provenance columns (nullable first so we can backfill from created_at)
ALTER TABLE gold.paper_trades_synthetic
    ADD COLUMN IF NOT EXISTS run_id uuid,                -- feeder run that FIRST inserted the row; immutable
    ADD COLUMN IF NOT EXISTS first_seen_at timestamptz,  -- first insert ts; immutable
    ADD COLUMN IF NOT EXISTS exit_run_id uuid,           -- feeder run that closed the row
    ADD COLUMN IF NOT EXISTS exit_updated_at timestamptz;-- when exit fields were last written

-- Legacy rows: provenance unknown (pre-append-only). run_id stays NULL (truthful),
-- first_seen_at falls back to created_at (best available lower bound).
UPDATE gold.paper_trades_synthetic
   SET first_seen_at = created_at
 WHERE first_seen_at IS NULL;

ALTER TABLE gold.paper_trades_synthetic
    ALTER COLUMN first_seen_at SET DEFAULT now(),
    ALTER COLUMN first_seen_at SET NOT NULL;

-- 2. Identity unique key for ON CONFLICT (strategy_id, ticker, entry_date)
--    Verified clean 2026-10-26: 282 rows, 36 strategies, 0 duplicates, ticker all non-null.
CREATE UNIQUE INDEX IF NOT EXISTS uniq_pts_strategy_ticker_entry
    ON gold.paper_trades_synthetic (strategy_id, ticker, entry_date);

-- 3. Feeder run audit table — every feeder run appends exactly one row.
CREATE TABLE IF NOT EXISTS gold.paper_feeder_runs (
    run_id            uuid PRIMARY KEY,
    feeder            text NOT NULL,        -- e.g. 'hk_ipo_c1_paper_feeder'
    strategy_id       text NOT NULL,
    run_ts            timestamptz NOT NULL DEFAULT now(),
    rows_considered   integer,              -- candidates taken by slot replay
    rows_inserted     integer,              -- new ledger rows (first_seen)
    rows_closed       integer,              -- open -> closed transitions written
    rows_orphaned     integer,              -- previously-written rows NOT reproduced this run (left untouched)
    entry_mismatches  integer,              -- restatement alarms: computed entry-side != stored (NOT applied)
    script_sha256     text,                 -- sha256 of the feeder script file
    git_sha           text,                 -- git rev-parse HEAD when in a repo, else NULL
    params            jsonb,                -- SLOTS/COST/BAND/ENTRY_DELAY/HOLD/POOL/PAPER_START snapshot
    notes             text
);
CREATE INDEX IF NOT EXISTS idx_paper_feeder_runs_strategy_ts
    ON gold.paper_feeder_runs (strategy_id, run_ts DESC);

COMMENT ON TABLE gold.paper_feeder_runs IS
'Append-only feeder audit. One row per feeder run. Ledger state at time T reconstructs as: '
'rows first_seen_at<=T, open iff exit_updated_at IS NULL OR exit_updated_at>T.';

COMMIT;
