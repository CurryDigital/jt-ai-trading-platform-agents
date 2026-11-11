-- 2026-10-26_unified_prices_pit_audit.sql
-- kanban t_c3327414 / follow-up to t_fd164803 (unified_ipo_* PIT)
--
-- silver.unified_prices (4.37M rows, 1.3 GB) was upsert-in-place with NO
-- point-in-time history. The 3636.HK restatement that broke C1
-- reproducibility (bar-20 39.60 restated; fdc 15.12 vs offer 30.0)
-- originated HERE; unified_ipo_* only audited the downstream symptom.
--
-- DESIGN DECISION (write-volume justified):
--   Measured 2026-10-26: the full-history silver merge upserts ~822k rows
--   per run, 2x/day (08:30 pipeline A + 22:30 US topup). Of those, only
--   ~600-800 are genuinely new bars; the rest are no-op restamps
--   (ON CONFLICT DO UPDATE rewrites identical values + updated_at=NOW()).
--   Genuine restatements are rare (17k rows on the 10-15 split backfill,
--   1.2k on 10-16).
--   (a) PER-ROW DIFF CAPTURE ON CHANGED ROWS ONLY  <-- CHOSEN
--       ~1-3k audit rows/day. Trigger compares value columns with explicit
--       IS NOT DISTINCT FROM (no to_jsonb cost on no-op rows); only real
--       changes build images and write audit+PIT rows.
--   (b) daily partition-level snapshots: REJECTED - 1.3 GB/day copy of a
--       4.37M-row table is pure bloat for <0.1% daily churn.
--   (c) bitemporal valid_from/valid_to on the base table: REJECTED -
--       rewrites the base schema, breaks every consumer query, and the
--       upsert-close-out doubles write amplification on the hot path.
--
-- VOLATILE-COLUMN SUPPRESSION mirrors the unified_ipo pattern: UPDATEs
-- touching only volatile columns (updated_at; created_at/id never change
-- on UPDATE) are NOT logged or PIT-versioned, so nightly no-op restamps
-- stay quiet.
--
-- SNAPSHOT-GUARD INTEGRATION: clean_unified_prices.py already refuses to
-- run without --snapshot-id / ETL_RUN_SNAPSHOT_ID (gold.etl_snapshot_log).
-- The script now also set_config('app.etl_source', snapshot_id) so every
-- audit/PIT row written by a full-history restate carries that snapshot id
-- in its source column - the audit trail ties back to the guard 1:1.
--
-- SEED-FROM-CURRENT-STATE is the baseline; pre-seed history is
-- UNRECOVERABLE (stated in the pit_meta row).
--
-- WRITER INVENTORY (all UPDATE/DELETE writers route through the audit path
-- automatically because capture is trigger-based, not script-based):
--   silver/clean_unified_prices.py   full-history upsert (snapshot-guarded)
--   silver/alias_fx_pairs.py         FX alias upsert (same pipeline)
--   silver/promote_ibkr.py           IBKR position-mark upsert (guarded WHERE)
--   silver/promote_ibkr_orders.py    IBKR mark upsert
--   oneoff split/spinoff backfills (gold.price_adjustment_factors flows),
--   phantom-delete oneoffs, backfill_etf_gold / backfill_rotation_universe_fix
--   gold/gold_builder.py             READER only (silver -> gold 14d mirror)
--
-- Column lists pinned from information_schema on 2026-10-26. If the base
-- table gains a column, mirror it into the pit table, the change-detection
-- comparison, and the reconstruction functions in a new migration.

BEGIN;

-- ============================================================
-- 1. Append-only restatement audit log
-- ============================================================
CREATE TABLE IF NOT EXISTS silver.unified_prices_audit (
    audit_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name text        NOT NULL,
    op         text        NOT NULL CHECK (op IN ('INSERT','UPDATE','DELETE')),
    pk         jsonb       NOT NULL,
    old_row    jsonb,
    new_row    jsonb,
    changed_at timestamptz NOT NULL DEFAULT now(),
    source     text
);
CREATE INDEX IF NOT EXISTS idx_unified_prices_audit_time
    ON silver.unified_prices_audit (changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_unified_prices_audit_pk
    ON silver.unified_prices_audit USING gin (pk);

CREATE OR REPLACE FUNCTION silver.fn_unified_prices_audit_guard()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'silver.unified_prices_audit is append-only: % is forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_unified_prices_audit_guard_row ON silver.unified_prices_audit;
CREATE TRIGGER trg_unified_prices_audit_guard_row
    BEFORE UPDATE OR DELETE ON silver.unified_prices_audit
    FOR EACH ROW EXECUTE FUNCTION silver.fn_unified_prices_audit_guard();

DROP TRIGGER IF EXISTS trg_unified_prices_audit_guard_trunc ON silver.unified_prices_audit;
CREATE TRIGGER trg_unified_prices_audit_guard_trunc
    BEFORE TRUNCATE ON silver.unified_prices_audit
    FOR EACH STATEMENT EXECUTE FUNCTION silver.fn_unified_prices_audit_guard();

-- ============================================================
-- 2. PIT history table (typed image; seeded from current state)
--    natural key: (ticker, date); volatile cols: [updated_at]
-- ============================================================
CREATE TABLE IF NOT EXISTS silver.unified_prices_pit (
    pit_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    LIKE silver.unified_prices,
    known_at   timestamptz NOT NULL DEFAULT now(),
    pit_op     text        NOT NULL CHECK (pit_op IN ('SEED','UPSERT','DELETE')),
    pit_source text
);
-- base-table defaults / NOT NULL must not leak into the pit table
-- (DELETE markers carry only key columns + pit metadata)
ALTER TABLE silver.unified_prices_pit ALTER COLUMN id DROP DEFAULT;
ALTER TABLE silver.unified_prices_pit ALTER COLUMN id DROP NOT NULL;
ALTER TABLE silver.unified_prices_pit ALTER COLUMN close DROP NOT NULL;
ALTER TABLE silver.unified_prices_pit ALTER COLUMN created_at DROP DEFAULT;
ALTER TABLE silver.unified_prices_pit ALTER COLUMN updated_at DROP DEFAULT;
CREATE INDEX IF NOT EXISTS idx_unified_prices_pit_key_time
    ON silver.unified_prices_pit (ticker, date, known_at DESC, pit_id DESC);

-- ============================================================
-- 3. Combined audit+PIT trigger (ONE fire per row, not two):
--    change detection via explicit column-wise IS NOT DISTINCT FROM
--    on value columns only (no jsonb built for no-op restamps)
-- ============================================================
CREATE OR REPLACE FUNCTION silver.fn_unified_prices_pit_audit_track()
RETURNS trigger AS $$
DECLARE
    v_src text;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- volatile-column suppression: updated_at-only restamps stay quiet
        -- (created_at and id are immutable on UPDATE by construction)
        IF OLD.asset_class    IS NOT DISTINCT FROM NEW.asset_class
       AND OLD.market         IS NOT DISTINCT FROM NEW.market
       AND OLD.open           IS NOT DISTINCT FROM NEW.open
       AND OLD.high           IS NOT DISTINCT FROM NEW.high
       AND OLD.low            IS NOT DISTINCT FROM NEW.low
       AND OLD.close          IS NOT DISTINCT FROM NEW.close
       AND OLD.volume         IS NOT DISTINCT FROM NEW.volume
       AND OLD.adjusted_close IS NOT DISTINCT FROM NEW.adjusted_close
       AND OLD.returns_1d     IS NOT DISTINCT FROM NEW.returns_1d
       AND OLD.returns_log    IS NOT DISTINCT FROM NEW.returns_log
       AND OLD.primary_source IS NOT DISTINCT FROM NEW.primary_source
       AND OLD.all_sources    IS NOT DISTINCT FROM NEW.all_sources
       AND OLD.source         IS NOT DISTINCT FROM NEW.source
        THEN
            RETURN NEW;
        END IF;
    END IF;

    v_src := COALESCE(NULLIF(current_setting('app.etl_source', true), ''),
                      NULLIF(current_setting('application_name', true), ''),
                      session_user);

    IF TG_OP = 'DELETE' THEN
        INSERT INTO silver.unified_prices_audit (table_name, op, pk, old_row, new_row, source)
        VALUES ('unified_prices', 'DELETE',
                jsonb_build_object('ticker', OLD.ticker, 'date', OLD.date),
                to_jsonb(OLD), NULL, v_src);
        INSERT INTO silver.unified_prices_pit (ticker, date, known_at, pit_op, pit_source)
        VALUES (OLD.ticker, OLD.date, now(), 'DELETE', v_src);
        RETURN OLD;
    END IF;

    -- INSERT or changed UPDATE: audit image + PIT UPSERT image
    INSERT INTO silver.unified_prices_audit (table_name, op, pk, old_row, new_row, source)
    VALUES ('unified_prices', TG_OP,
            jsonb_build_object('ticker', NEW.ticker, 'date', NEW.date),
            CASE WHEN TG_OP = 'UPDATE' THEN to_jsonb(OLD) END,
            to_jsonb(NEW), v_src);
    INSERT INTO silver.unified_prices_pit
        (id, ticker, asset_class, market, date, open, high, low, close, volume,
         adjusted_close, returns_1d, returns_log, primary_source, all_sources,
         created_at, updated_at, source, known_at, pit_op, pit_source)
    VALUES
        (NEW.id, NEW.ticker, NEW.asset_class, NEW.market, NEW.date, NEW.open,
         NEW.high, NEW.low, NEW.close, NEW.volume, NEW.adjusted_close,
         NEW.returns_1d, NEW.returns_log, NEW.primary_source, NEW.all_sources,
         NEW.created_at, NEW.updated_at, NEW.source, now(), 'UPSERT', v_src);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_unified_prices_pit_audit ON silver.unified_prices;
CREATE TRIGGER trg_unified_prices_pit_audit
    AFTER INSERT OR UPDATE OR DELETE ON silver.unified_prices
    FOR EACH ROW
    EXECUTE FUNCTION silver.fn_unified_prices_pit_audit_track();

-- ============================================================
-- 4. Seed current state as the PIT baseline
--    (pre-seed history is UNRECOVERABLE - see pit_meta)
-- ============================================================
INSERT INTO silver.unified_prices_pit
    (id, ticker, asset_class, market, date, open, high, low, close, volume,
     adjusted_close, returns_1d, returns_log, primary_source, all_sources,
     created_at, updated_at, source, known_at, pit_op, pit_source)
SELECT id, ticker, asset_class, market, date, open, high, low, close, volume,
       adjusted_close, returns_1d, returns_log, primary_source, all_sources,
       created_at, updated_at, source, now(), 'SEED',
       'migrate_2026-10-26_unified_prices_pit_audit'
FROM silver.unified_prices b
WHERE NOT EXISTS (SELECT 1 FROM silver.unified_prices_pit s WHERE s.pit_op = 'SEED');

-- ============================================================
-- 5. Point-in-time reconstruction
-- ============================================================
-- per-ticker series as known at ts (cheap: uses idx_unified_prices_pit_key_time)
CREATE OR REPLACE FUNCTION silver.unified_prices_ticker_asof(p_ticker text, ts timestamptz)
RETURNS SETOF silver.unified_prices AS $$
    SELECT id, ticker, asset_class, market, date, open, high, low, close, volume,
           adjusted_close, returns_1d, returns_log, primary_source, all_sources,
           created_at, updated_at, source
    FROM (
        SELECT DISTINCT ON (date) p.*
        FROM silver.unified_prices_pit p
        WHERE p.ticker = p_ticker AND p.known_at <= ts
        ORDER BY date, p.known_at DESC, p.pit_id DESC
    ) s
    WHERE s.pit_op <> 'DELETE'
    ORDER BY date;
$$ LANGUAGE sql STABLE;

-- whole-table content as known at ts (expensive on 4.3M+ rows; prefer the
-- per-ticker variant for research queries)
CREATE OR REPLACE FUNCTION silver.unified_prices_asof(ts timestamptz)
RETURNS SETOF silver.unified_prices AS $$
    SELECT id, ticker, asset_class, market, date, open, high, low, close, volume,
           adjusted_close, returns_1d, returns_log, primary_source, all_sources,
           created_at, updated_at, source
    FROM (
        SELECT DISTINCT ON (ticker, date) p.*
        FROM silver.unified_prices_pit p
        WHERE p.known_at <= ts
        ORDER BY ticker, date, p.known_at DESC, p.pit_id DESC
    ) s
    WHERE s.pit_op <> 'DELETE'
    ORDER BY ticker, date;
$$ LANGUAGE sql STABLE;

-- ============================================================
-- 6. pit_meta rows: scope decision + enabled_at (and retire the
--    "NOT yet PIT-versioned" note from t_fd164803)
-- ============================================================
INSERT INTO silver.unified_ipo_pit_meta (key, value, note) VALUES
  ('unified_prices_pit',
   jsonb_build_object(
     'enabled_at', now(),
     'scope', 'silver.unified_prices',
     'design', 'per-row diff capture on changed rows only (IS DISTINCT FROM on value columns); combined audit+PIT trigger',
     'seed', 'current_state',
     'pre_seed_history', 'UNRECOVERABLE',
     'kanban', 't_c3327414'),
   'silver.unified_prices PIT + restatement audit LIVE (kanban t_c3327414). '
   'Seeded from current state 2026-10-26; pre-seed restatement history '
   '(incl. the 3636.HK bar-20/fdc restatement) is UNRECOVERABLE. '
   'Full-history restates still require --snapshot-id (gold.etl_snapshot_log) '
   'per clean_unified_prices.py; audit/PIT rows carry that id via app.etl_source.')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, note = EXCLUDED.note,
                                updated_at = now();

UPDATE silver.unified_ipo_pit_meta
SET value = '["unified_ipo_calendar","unified_ipo_performance","unified_ipo_grey_market","unified_prices"]'::jsonb,
    note = 'PIT scope. unified_prices added 2026-10-26 (kanban t_c3327414): '
           'per-row diff capture, seeded from current state; pre-seed history unrecoverable.',
    updated_at = now()
WHERE key = 'pit_scope';

INSERT INTO gold.etl_snapshot_log (snapshot_id, scope, script, pre_rows, post_rows, note)
SELECT 'pit_seed_20261026_unified_prices',
       'silver.unified_prices',
       'migrations/2026-10-26_unified_prices_pit_audit.sql',
       (SELECT count(*) FROM silver.unified_prices),
       (SELECT count(*) FROM silver.unified_prices_pit),
       'PIT baseline seeded (pit_op=SEED); combined audit+PIT trigger live'
ON CONFLICT (snapshot_id) DO NOTHING;

COMMIT;
