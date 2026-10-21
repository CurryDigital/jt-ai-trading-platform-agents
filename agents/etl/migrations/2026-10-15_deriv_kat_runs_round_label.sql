-- 2026-10-15: derivatives KAT run batching metadata.
-- Metadata only; existing rows' params/metrics/verdict are untouched.
ALTER TABLE deriv.kat_runs ADD COLUMN IF NOT EXISTS round_label text;
