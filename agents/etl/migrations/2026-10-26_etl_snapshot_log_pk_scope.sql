-- 2026-10-26_etl_snapshot_log_pk_scope.sql
-- kanban t_4e11c086
--
-- Root cause: gold.etl_snapshot_log PK was snapshot_id ALONE, but
-- run_stage.py issues ONE ETL_RUN_SNAPSHOT_ID per run shared by all steps.
-- Every step that logs a snapshot upserts ON CONFLICT (snapshot_id), so the
-- LAST writer in a run clobbers earlier steps' post_rows/note evidence.
-- Verified live: gold/equity/build_earnings_signals.py (runs after the silver
-- merge in the daily manifest) overwrote the merge row's post_rows with the
-- gold.sue_scores count on run_daily_2026101{9,20,21,22,23},run_daily_20261026
-- (post_rows 17801/17878 = sue_scores counts, note string from
-- build_earnings_signals.py:122). scope/script survived because the conflict
-- clause never updated them, making the row look like the merge wrote 17.8k
-- rows when the real merge post_rows was ~4.36M.
--
-- Fix: composite PK (snapshot_id, scope) -> one row per (run, step).
-- snapshot_id itself is UNCHANGED, so the app.etl_source -> audit.source
-- attribution chain (t_c3327414) keeps resolving to this table.
--
-- Historical clobbered rows CANNOT be restated (the merge's real post_rows
-- was overwritten in place). They are flagged in `note` below and the
-- corruption window is recorded in silver.unified_ipo_pit_meta.

BEGIN;

-- 1. Composite PK ------------------------------------------------------------
ALTER TABLE gold.etl_snapshot_log DROP CONSTRAINT etl_snapshot_log_pkey;
ALTER TABLE gold.etl_snapshot_log ADD PRIMARY KEY (snapshot_id, scope);

-- 2. Flag corrupted historical rows (idempotent) ------------------------------
-- Pattern: merge-scope row whose post_rows is impossibly small for a
-- full-history merge (< 100k vs real ~4.36M) under a scheduled run_* id.
-- pre_rows/post_max_date are INTACT (conflict clause never touched them);
-- only post_rows and note were destroyed.
UPDATE gold.etl_snapshot_log
SET note = note || ' [CORRUPTED post_rows+note: overwritten by '
       || 'gold/equity/build_earnings_signals.py log_snapshot under shared '
       || 'ETL_RUN_SNAPSHOT_ID (pre t_4e11c086 PK fix). post_rows shown is the '
       || 'gold.sue_scores count, NOT the merge post_rows (~4.36M, see pre_rows '
       || '+1d delta). Unrecoverable.]'
WHERE scope = 'silver.unified_prices full-history merge'
  AND post_rows < 100000
  AND snapshot_id LIKE 'run_%'
  AND note NOT LIKE '%CORRUPTED post_rows%';

-- 3. Record the corruption window in pit_meta ---------------------------------
INSERT INTO silver.unified_ipo_pit_meta (key, value, note) VALUES
  ('etl_snapshot_log_pk_fix',
   jsonb_build_object(
     'fixed_at', now(),
     'kanban', 't_4e11c086',
     'change', 'gold.etl_snapshot_log PK snapshot_id -> (snapshot_id, scope)',
     'corrupted_rows', 'run_daily_2026101{9,20,21,22,23}, run_daily_20261026',
     'corruption', 'merge-scope rows post_rows/note clobbered by build_earnings_signals.py log_snapshot (shared ETL_RUN_SNAPSHOT_ID); post_rows actually = gold.sue_scores count',
     'restatable', false),
   'gold.etl_snapshot_log PK collision fixed 2026-10-26 (kanban t_4e11c086): '
   'PK is now (snapshot_id, scope), one row per (run, step). Pre-fix run_* rows '
   'with scope=''silver.unified_prices full-history merge'' and post_rows < 100k '
   'are CORRUPTED (post_rows = gold.sue_scores count; merge evidence destroyed '
   'in place, unrecoverable) and are flagged in their note field.')
ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, note = EXCLUDED.note,
                                updated_at = now();

COMMIT;
