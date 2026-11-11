-- 2026-10-26_unified_ipo_pit_audit.sql
-- kanban t_fd164803 / c1_trust_audit_2026-10-26.md Finding 4
--
-- silver.unified_ipo_* was upsert/delete-in-place: restatements (e.g. 3636.HK
-- full price-history + D1 close restate after the 2026-09-22 C1 backtest run)
-- silently rewrote history, making published backtests non-reproducible and
-- flattering strategies (a -19.4% loser vanished from revised data).
--
-- This migration adds:
--   1. silver.unified_ipo_audit          - append-only restatement audit log
--      (table_name, op, pk, old_row, new_row, changed_at, source) fed by
--      triggers on every unified_ipo_* table; UPDATE/DELETE/TRUNCATE on the
--      audit table itself are rejected by guard triggers.
--   2. silver.unified_ipo_<name>_pit     - point-in-time history tables:
--      full typed row image + known_at + pit_op (SEED/UPSERT/DELETE). Seeded
--      from current state with pit_op='SEED' (known_at = migration time).
--      PIT accumulation starts now; pre-seed history is NOT recoverable.
--   3. silver.unified_ipo_<name>_asof(ts) - point-in-time reconstruction:
--      latest image per natural key with known_at <= ts, minus deletes.
--   4. silver.unified_ipo_pit_meta        - pit_enabled_at + policy marker:
--      ALL metrics computed from these tables before pit_enabled_at are
--      UNVERIFIED_NON_PIT.
--
-- Trigger noise control: UPDATEs that change only volatile columns
-- (updated_at) are NOT logged/pit-versioned, so nightly no-op restamps stay
-- quiet. The performance writer's blanket DELETE+reinsert was replaced by
-- purge-only-stale in build_ipo_performance.py (same final-state semantics).
--
-- Column lists below are pinned from information_schema on 2026-10-26.
-- If a base table gains a column, mirror it into the _pit table and the
-- pit trigger function in a new migration.

BEGIN;

-- ============================================================
-- 1. Append-only restatement audit log
-- ============================================================
CREATE TABLE IF NOT EXISTS silver.unified_ipo_audit (
    audit_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    table_name text        NOT NULL,
    op         text        NOT NULL CHECK (op IN ('INSERT','UPDATE','DELETE')),
    pk         jsonb       NOT NULL,
    old_row    jsonb,
    new_row    jsonb,
    changed_at timestamptz NOT NULL DEFAULT now(),
    source     text
);
CREATE INDEX IF NOT EXISTS idx_unified_ipo_audit_table_time
    ON silver.unified_ipo_audit (table_name, changed_at DESC);
CREATE INDEX IF NOT EXISTS idx_unified_ipo_audit_pk
    ON silver.unified_ipo_audit USING gin (pk);

CREATE OR REPLACE FUNCTION silver.fn_unified_ipo_audit_guard()
RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'silver.unified_ipo_audit is append-only: % is forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_unified_ipo_audit_guard_row ON silver.unified_ipo_audit;
CREATE TRIGGER trg_unified_ipo_audit_guard_row
    BEFORE UPDATE OR DELETE ON silver.unified_ipo_audit
    FOR EACH ROW EXECUTE FUNCTION silver.fn_unified_ipo_audit_guard();

DROP TRIGGER IF EXISTS trg_unified_ipo_audit_guard_trunc ON silver.unified_ipo_audit;
CREATE TRIGGER trg_unified_ipo_audit_guard_trunc
    BEFORE TRUNCATE ON silver.unified_ipo_audit
    FOR EACH STATEMENT EXECUTE FUNCTION silver.fn_unified_ipo_audit_guard();

-- ============================================================
-- 2. Generic audit trigger function
--    TG_ARGV[0] = comma-separated pk columns
--    TG_ARGV[1] = comma-separated volatile columns excluded from the
--                no-op UPDATE comparison ('' = none)
-- ============================================================
CREATE OR REPLACE FUNCTION silver.fn_unified_ipo_audit_track()
RETURNS trigger AS $$
DECLARE
    v_old      jsonb;
    v_new      jsonb;
    v_pk       jsonb;
    v_volatile text[];
    v_src      text;
BEGIN
    v_volatile := CASE WHEN TG_ARGV[1] = '' THEN '{}'::text[]
                       ELSE string_to_array(TG_ARGV[1], ',') END;
    v_src := COALESCE(NULLIF(current_setting('app.etl_source', true), ''),
                      NULLIF(current_setting('application_name', true), ''),
                      session_user);
    IF TG_OP = 'UPDATE' THEN
        v_old := to_jsonb(OLD);
        v_new := to_jsonb(NEW);
        -- suppress pure volatile-column restamps (nightly no-op re-stamps)
        IF (v_old - v_volatile) IS NOT DISTINCT FROM (v_new - v_volatile) THEN
            RETURN NEW;
        END IF;
    ELSIF TG_OP = 'INSERT' THEN
        v_new := to_jsonb(NEW);
    ELSE -- DELETE
        v_old := to_jsonb(OLD);
    END IF;

    SELECT jsonb_object_agg(key, value) INTO v_pk
    FROM jsonb_each(COALESCE(v_new, v_old))
    WHERE key = ANY (string_to_array(TG_ARGV[0], ','));

    INSERT INTO silver.unified_ipo_audit (table_name, op, pk, old_row, new_row, source)
    VALUES (TG_TABLE_NAME, TG_OP, v_pk, v_old, v_new, v_src);

    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- 3. PIT history for silver.unified_ipo_calendar
--    natural key: (ticker, listing_date); volatile cols: ['updated_at']
-- ============================================================
CREATE TABLE IF NOT EXISTS silver.unified_ipo_calendar_pit (
    pit_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    LIKE silver.unified_ipo_calendar,
    known_at   timestamptz NOT NULL DEFAULT now(),
    pit_op     text        NOT NULL CHECK (pit_op IN ('SEED','UPSERT','DELETE')),
    pit_source text
);
-- base-table defaults (sequences) must not leak into the pit table
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN id DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN ticker DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN stock_name DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN listing_date DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN offer_price DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN currency DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN market_cap_hkd DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN market_cap_usd DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN sector DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN sub_sector DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN sponsor DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN underwriters DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN shares_offered DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN greenshoe_shares DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN total_shares_post_ipo DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN free_float_pct DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN board DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN oversubscription_retail DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN oversubscription_institutional DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN cornerstone_total_pct DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN cornerstone_investors_count DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN lockup_period_days DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN greenshoe_pct DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN first_seen_at DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN updated_at DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN offer_price_low DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN offer_price_high DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN lot_size DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN one_lot_success_pct DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN funds_raised_hkd DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN data_source DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN grey_close DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN grey_high DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN grey_low DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN grey_turnover DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN grey_session_date DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN grey_source DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN applied_lots_for_1_lot DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN price_range_source DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN fixed_price DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN stock_name_zh DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN application_start DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN application_end DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN allotment_date DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN a_twin_ticker DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN a_twin_status DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN a_twin_source DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN nav_per_share_hkd DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN nav_asof DROP DEFAULT;
ALTER TABLE silver.unified_ipo_calendar_pit ALTER COLUMN nav_source DROP DEFAULT;
CREATE INDEX IF NOT EXISTS idx_unified_ipo_calendar_pit_key_time
    ON silver.unified_ipo_calendar_pit (ticker, listing_date, known_at DESC, pit_id DESC);

CREATE OR REPLACE FUNCTION silver.fn_unified_ipo_calendar_pit_track()
RETURNS trigger AS $$
DECLARE
    v_src text;
BEGIN
    v_src := COALESCE(NULLIF(current_setting('app.etl_source', true), ''),
                      NULLIF(current_setting('application_name', true), ''),
                      session_user);
    IF TG_OP = 'DELETE' THEN
        INSERT INTO silver.unified_ipo_calendar_pit (ticker, listing_date, known_at, pit_op, pit_source)
        VALUES (OLD.ticker, OLD.listing_date, now(), 'DELETE', v_src);
        RETURN OLD;
    END IF;
    -- suppress pure volatile-column restamps (same rule as the audit trigger)
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(OLD) - ARRAY['updated_at']) IS NOT DISTINCT FROM (to_jsonb(NEW) - ARRAY['updated_at']) THEN
        RETURN NEW;
    END IF;
    INSERT INTO silver.unified_ipo_calendar_pit (id, ticker, stock_name, listing_date, offer_price, currency, market_cap_hkd, market_cap_usd, sector, sub_sector, sponsor, underwriters, shares_offered, greenshoe_shares, total_shares_post_ipo, free_float_pct, board, oversubscription_retail, oversubscription_institutional, cornerstone_total_pct, cornerstone_investors_count, lockup_period_days, greenshoe_pct, first_seen_at, updated_at, offer_price_low, offer_price_high, lot_size, one_lot_success_pct, funds_raised_hkd, data_source, grey_close, grey_high, grey_low, grey_turnover, grey_session_date, grey_source, applied_lots_for_1_lot, price_range_source, fixed_price, stock_name_zh, application_start, application_end, allotment_date, a_twin_ticker, a_twin_status, a_twin_source, nav_per_share_hkd, nav_asof, nav_source, known_at, pit_op, pit_source)
    VALUES (NEW.id, NEW.ticker, NEW.stock_name, NEW.listing_date, NEW.offer_price, NEW.currency, NEW.market_cap_hkd, NEW.market_cap_usd, NEW.sector, NEW.sub_sector, NEW.sponsor, NEW.underwriters, NEW.shares_offered, NEW.greenshoe_shares, NEW.total_shares_post_ipo, NEW.free_float_pct, NEW.board, NEW.oversubscription_retail, NEW.oversubscription_institutional, NEW.cornerstone_total_pct, NEW.cornerstone_investors_count, NEW.lockup_period_days, NEW.greenshoe_pct, NEW.first_seen_at, NEW.updated_at, NEW.offer_price_low, NEW.offer_price_high, NEW.lot_size, NEW.one_lot_success_pct, NEW.funds_raised_hkd, NEW.data_source, NEW.grey_close, NEW.grey_high, NEW.grey_low, NEW.grey_turnover, NEW.grey_session_date, NEW.grey_source, NEW.applied_lots_for_1_lot, NEW.price_range_source, NEW.fixed_price, NEW.stock_name_zh, NEW.application_start, NEW.application_end, NEW.allotment_date, NEW.a_twin_ticker, NEW.a_twin_status, NEW.a_twin_source, NEW.nav_per_share_hkd, NEW.nav_asof, NEW.nav_source, now(), 'UPSERT', v_src);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_unified_ipo_calendar_audit ON silver.unified_ipo_calendar;
CREATE TRIGGER trg_unified_ipo_calendar_audit
    AFTER INSERT OR UPDATE OR DELETE ON silver.unified_ipo_calendar
    FOR EACH ROW
    EXECUTE FUNCTION silver.fn_unified_ipo_audit_track('ticker,listing_date', 'updated_at');

DROP TRIGGER IF EXISTS trg_unified_ipo_calendar_pit ON silver.unified_ipo_calendar;
CREATE TRIGGER trg_unified_ipo_calendar_pit
    AFTER INSERT OR UPDATE OR DELETE ON silver.unified_ipo_calendar
    FOR EACH ROW
    EXECUTE FUNCTION silver.fn_unified_ipo_calendar_pit_track();

-- seed current state as the PIT baseline (pre-seed history is unrecoverable)
INSERT INTO silver.unified_ipo_calendar_pit (id, ticker, stock_name, listing_date, offer_price, currency, market_cap_hkd, market_cap_usd, sector, sub_sector, sponsor, underwriters, shares_offered, greenshoe_shares, total_shares_post_ipo, free_float_pct, board, oversubscription_retail, oversubscription_institutional, cornerstone_total_pct, cornerstone_investors_count, lockup_period_days, greenshoe_pct, first_seen_at, updated_at, offer_price_low, offer_price_high, lot_size, one_lot_success_pct, funds_raised_hkd, data_source, grey_close, grey_high, grey_low, grey_turnover, grey_session_date, grey_source, applied_lots_for_1_lot, price_range_source, fixed_price, stock_name_zh, application_start, application_end, allotment_date, a_twin_ticker, a_twin_status, a_twin_source, nav_per_share_hkd, nav_asof, nav_source, known_at, pit_op, pit_source)
SELECT id, ticker, stock_name, listing_date, offer_price, currency, market_cap_hkd, market_cap_usd, sector, sub_sector, sponsor, underwriters, shares_offered, greenshoe_shares, total_shares_post_ipo, free_float_pct, board, oversubscription_retail, oversubscription_institutional, cornerstone_total_pct, cornerstone_investors_count, lockup_period_days, greenshoe_pct, first_seen_at, updated_at, offer_price_low, offer_price_high, lot_size, one_lot_success_pct, funds_raised_hkd, data_source, grey_close, grey_high, grey_low, grey_turnover, grey_session_date, grey_source, applied_lots_for_1_lot, price_range_source, fixed_price, stock_name_zh, application_start, application_end, allotment_date, a_twin_ticker, a_twin_status, a_twin_source, nav_per_share_hkd, nav_asof, nav_source, now(), 'SEED', 'migrate_2026-10-26_unified_ipo_pit_audit'
FROM silver.unified_ipo_calendar b
WHERE NOT EXISTS (SELECT 1 FROM silver.unified_ipo_calendar_pit s WHERE s.pit_op = 'SEED');

-- point-in-time reconstruction: table content as known at ts
CREATE OR REPLACE FUNCTION silver.unified_ipo_calendar_asof(ts timestamptz)
RETURNS SETOF silver.unified_ipo_calendar AS $$
    SELECT id, ticker, stock_name, listing_date, offer_price, currency, market_cap_hkd, market_cap_usd, sector, sub_sector, sponsor, underwriters, shares_offered, greenshoe_shares, total_shares_post_ipo, free_float_pct, board, oversubscription_retail, oversubscription_institutional, cornerstone_total_pct, cornerstone_investors_count, lockup_period_days, greenshoe_pct, first_seen_at, updated_at, offer_price_low, offer_price_high, lot_size, one_lot_success_pct, funds_raised_hkd, data_source, grey_close, grey_high, grey_low, grey_turnover, grey_session_date, grey_source, applied_lots_for_1_lot, price_range_source, fixed_price, stock_name_zh, application_start, application_end, allotment_date, a_twin_ticker, a_twin_status, a_twin_source, nav_per_share_hkd, nav_asof, nav_source
    FROM (
        SELECT DISTINCT ON (ticker, listing_date) p.*
        FROM silver.unified_ipo_calendar_pit p
        WHERE p.known_at <= ts
        ORDER BY ticker, listing_date, p.known_at DESC, p.pit_id DESC
    ) s
    WHERE s.pit_op <> 'DELETE'
    ORDER BY ticker, listing_date;
$$ LANGUAGE sql STABLE;

-- ============================================================
-- 3. PIT history for silver.unified_ipo_performance
--    natural key: (ticker, listing_date); volatile cols: none
-- ============================================================
CREATE TABLE IF NOT EXISTS silver.unified_ipo_performance_pit (
    pit_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    LIKE silver.unified_ipo_performance,
    known_at   timestamptz NOT NULL DEFAULT now(),
    pit_op     text        NOT NULL CHECK (pit_op IN ('SEED','UPSERT','DELETE')),
    pit_source text
);
-- base-table defaults (sequences) must not leak into the pit table
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN ticker DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN listing_date DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN return_1m DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN return_3m DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN offer_price DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN first_day_date DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN first_day_open DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN first_day_high DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN first_day_low DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN first_day_close DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN first_day_volume DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN return_1d DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN return_10d DROP DEFAULT;
ALTER TABLE silver.unified_ipo_performance_pit ALTER COLUMN return_20d DROP DEFAULT;
CREATE INDEX IF NOT EXISTS idx_unified_ipo_performance_pit_key_time
    ON silver.unified_ipo_performance_pit (ticker, listing_date, known_at DESC, pit_id DESC);

CREATE OR REPLACE FUNCTION silver.fn_unified_ipo_performance_pit_track()
RETURNS trigger AS $$
DECLARE
    v_src text;
BEGIN
    v_src := COALESCE(NULLIF(current_setting('app.etl_source', true), ''),
                      NULLIF(current_setting('application_name', true), ''),
                      session_user);
    IF TG_OP = 'DELETE' THEN
        INSERT INTO silver.unified_ipo_performance_pit (ticker, listing_date, known_at, pit_op, pit_source)
        VALUES (OLD.ticker, OLD.listing_date, now(), 'DELETE', v_src);
        RETURN OLD;
    END IF;
    -- suppress pure volatile-column restamps (same rule as the audit trigger)
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(OLD) - '{}'::text[]) IS NOT DISTINCT FROM (to_jsonb(NEW) - '{}'::text[]) THEN
        RETURN NEW;
    END IF;
    INSERT INTO silver.unified_ipo_performance_pit (ticker, listing_date, return_1m, return_3m, offer_price, first_day_date, first_day_open, first_day_high, first_day_low, first_day_close, first_day_volume, return_1d, return_10d, return_20d, known_at, pit_op, pit_source)
    VALUES (NEW.ticker, NEW.listing_date, NEW.return_1m, NEW.return_3m, NEW.offer_price, NEW.first_day_date, NEW.first_day_open, NEW.first_day_high, NEW.first_day_low, NEW.first_day_close, NEW.first_day_volume, NEW.return_1d, NEW.return_10d, NEW.return_20d, now(), 'UPSERT', v_src);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_unified_ipo_performance_audit ON silver.unified_ipo_performance;
CREATE TRIGGER trg_unified_ipo_performance_audit
    AFTER INSERT OR UPDATE OR DELETE ON silver.unified_ipo_performance
    FOR EACH ROW
    EXECUTE FUNCTION silver.fn_unified_ipo_audit_track('ticker,listing_date', '');

DROP TRIGGER IF EXISTS trg_unified_ipo_performance_pit ON silver.unified_ipo_performance;
CREATE TRIGGER trg_unified_ipo_performance_pit
    AFTER INSERT OR UPDATE OR DELETE ON silver.unified_ipo_performance
    FOR EACH ROW
    EXECUTE FUNCTION silver.fn_unified_ipo_performance_pit_track();

-- seed current state as the PIT baseline (pre-seed history is unrecoverable)
INSERT INTO silver.unified_ipo_performance_pit (ticker, listing_date, return_1m, return_3m, offer_price, first_day_date, first_day_open, first_day_high, first_day_low, first_day_close, first_day_volume, return_1d, return_10d, return_20d, known_at, pit_op, pit_source)
SELECT ticker, listing_date, return_1m, return_3m, offer_price, first_day_date, first_day_open, first_day_high, first_day_low, first_day_close, first_day_volume, return_1d, return_10d, return_20d, now(), 'SEED', 'migrate_2026-10-26_unified_ipo_pit_audit'
FROM silver.unified_ipo_performance b
WHERE NOT EXISTS (SELECT 1 FROM silver.unified_ipo_performance_pit s WHERE s.pit_op = 'SEED');

-- point-in-time reconstruction: table content as known at ts
CREATE OR REPLACE FUNCTION silver.unified_ipo_performance_asof(ts timestamptz)
RETURNS SETOF silver.unified_ipo_performance AS $$
    SELECT ticker, listing_date, return_1m, return_3m, offer_price, first_day_date, first_day_open, first_day_high, first_day_low, first_day_close, first_day_volume, return_1d, return_10d, return_20d
    FROM (
        SELECT DISTINCT ON (ticker, listing_date) p.*
        FROM silver.unified_ipo_performance_pit p
        WHERE p.known_at <= ts
        ORDER BY ticker, listing_date, p.known_at DESC, p.pit_id DESC
    ) s
    WHERE s.pit_op <> 'DELETE'
    ORDER BY ticker, listing_date;
$$ LANGUAGE sql STABLE;

-- ============================================================
-- 3. PIT history for silver.unified_ipo_grey_market
--    natural key: (ticker); volatile cols: ['updated_at']
-- ============================================================
CREATE TABLE IF NOT EXISTS silver.unified_ipo_grey_market_pit (
    pit_id     bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    LIKE silver.unified_ipo_grey_market,
    known_at   timestamptz NOT NULL DEFAULT now(),
    pit_op     text        NOT NULL CHECK (pit_op IN ('SEED','UPSERT','DELETE')),
    pit_source text
);
-- base-table defaults (sequences) must not leak into the pit table
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN ticker DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN grey_session_date DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN grey_open DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN grey_high DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN grey_low DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN grey_close DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN grey_turnover DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN grey_return_pct DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN source DROP DEFAULT;
ALTER TABLE silver.unified_ipo_grey_market_pit ALTER COLUMN updated_at DROP DEFAULT;
CREATE INDEX IF NOT EXISTS idx_unified_ipo_grey_market_pit_key_time
    ON silver.unified_ipo_grey_market_pit (ticker, known_at DESC, pit_id DESC);

CREATE OR REPLACE FUNCTION silver.fn_unified_ipo_grey_market_pit_track()
RETURNS trigger AS $$
DECLARE
    v_src text;
BEGIN
    v_src := COALESCE(NULLIF(current_setting('app.etl_source', true), ''),
                      NULLIF(current_setting('application_name', true), ''),
                      session_user);
    IF TG_OP = 'DELETE' THEN
        INSERT INTO silver.unified_ipo_grey_market_pit (ticker, known_at, pit_op, pit_source)
        VALUES (OLD.ticker, now(), 'DELETE', v_src);
        RETURN OLD;
    END IF;
    -- suppress pure volatile-column restamps (same rule as the audit trigger)
    IF TG_OP = 'UPDATE'
       AND (to_jsonb(OLD) - ARRAY['updated_at']) IS NOT DISTINCT FROM (to_jsonb(NEW) - ARRAY['updated_at']) THEN
        RETURN NEW;
    END IF;
    INSERT INTO silver.unified_ipo_grey_market_pit (ticker, grey_session_date, grey_open, grey_high, grey_low, grey_close, grey_turnover, grey_return_pct, source, updated_at, known_at, pit_op, pit_source)
    VALUES (NEW.ticker, NEW.grey_session_date, NEW.grey_open, NEW.grey_high, NEW.grey_low, NEW.grey_close, NEW.grey_turnover, NEW.grey_return_pct, NEW.source, NEW.updated_at, now(), 'UPSERT', v_src);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_unified_ipo_grey_market_audit ON silver.unified_ipo_grey_market;
CREATE TRIGGER trg_unified_ipo_grey_market_audit
    AFTER INSERT OR UPDATE OR DELETE ON silver.unified_ipo_grey_market
    FOR EACH ROW
    EXECUTE FUNCTION silver.fn_unified_ipo_audit_track('ticker', 'updated_at');

DROP TRIGGER IF EXISTS trg_unified_ipo_grey_market_pit ON silver.unified_ipo_grey_market;
CREATE TRIGGER trg_unified_ipo_grey_market_pit
    AFTER INSERT OR UPDATE OR DELETE ON silver.unified_ipo_grey_market
    FOR EACH ROW
    EXECUTE FUNCTION silver.fn_unified_ipo_grey_market_pit_track();

-- seed current state as the PIT baseline (pre-seed history is unrecoverable)
INSERT INTO silver.unified_ipo_grey_market_pit (ticker, grey_session_date, grey_open, grey_high, grey_low, grey_close, grey_turnover, grey_return_pct, source, updated_at, known_at, pit_op, pit_source)
SELECT ticker, grey_session_date, grey_open, grey_high, grey_low, grey_close, grey_turnover, grey_return_pct, source, updated_at, now(), 'SEED', 'migrate_2026-10-26_unified_ipo_pit_audit'
FROM silver.unified_ipo_grey_market b
WHERE NOT EXISTS (SELECT 1 FROM silver.unified_ipo_grey_market_pit s WHERE s.pit_op = 'SEED');

-- point-in-time reconstruction: table content as known at ts
CREATE OR REPLACE FUNCTION silver.unified_ipo_grey_market_asof(ts timestamptz)
RETURNS SETOF silver.unified_ipo_grey_market AS $$
    SELECT ticker, grey_session_date, grey_open, grey_high, grey_low, grey_close, grey_turnover, grey_return_pct, source, updated_at
    FROM (
        SELECT DISTINCT ON (ticker) p.*
        FROM silver.unified_ipo_grey_market_pit p
        WHERE p.known_at <= ts
        ORDER BY ticker, p.known_at DESC, p.pit_id DESC
    ) s
    WHERE s.pit_op <> 'DELETE'
    ORDER BY ticker;
$$ LANGUAGE sql STABLE;

-- ============================================================
-- 4. PIT status marker (requirement 3: pre-fix metrics UNVERIFIED_NON_PIT)
-- ============================================================
CREATE TABLE IF NOT EXISTS silver.unified_ipo_pit_meta (
    key        text PRIMARY KEY,
    value      jsonb       NOT NULL,
    note       text,
    updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO silver.unified_ipo_pit_meta (key, value, note) VALUES
  ('pit_enabled_at', to_jsonb(now()),
   'PIT snapshotting + restatement audit deployed (kanban t_fd164803).'),
  ('pre_fix_metrics_policy', '"UNVERIFIED_NON_PIT"'::jsonb,
   'ALL metrics/backtests computed from silver.unified_ipo_* before pit_enabled_at '
   'are UNVERIFIED_NON_PIT: tables were restate-in-place (c1_trust_audit_2026-10-26 '
   'Finding 4; 3636.HK history + D1 close restated post-2026-09-22 C1 run). '
   'Recompute against silver.unified_ipo_*_asof(ts) before trusting any pre-fix result.'),
  ('pit_scope', '["unified_ipo_calendar","unified_ipo_performance","unified_ipo_grey_market"]'::jsonb,
   'silver.unified_prices (source of the 3636.HK price restatement) is NOT yet '
   'PIT-versioned - tracked as follow-up work.')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, note = EXCLUDED.note,
                                updated_at = now();

INSERT INTO gold.etl_snapshot_log (snapshot_id, scope, script, pre_rows, post_rows, note)
SELECT 'pit_seed_20261026_' || t,
       'silver.' || t,
       'migrations/2026-10-26_unified_ipo_pit_audit.sql',
       (SELECT count(*) FROM silver.unified_ipo_audit),
       NULL,
       'PIT baseline seeded (pit_op=SEED); audit + pit triggers live'
FROM (VALUES ('unified_ipo_calendar'), ('unified_ipo_performance'), ('unified_ipo_grey_market')) v(t)
ON CONFLICT (snapshot_id) DO NOTHING;

COMMIT;
