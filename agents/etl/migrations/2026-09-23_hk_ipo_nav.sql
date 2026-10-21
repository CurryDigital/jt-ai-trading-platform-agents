-- 2026-09-23_hk_ipo_nav.sql (kanban t_ef6032f4)
-- Offer-price-to-NAV (pro-forma adjusted net tangible assets per share) for HK IPOs.
-- Source: prospectus "Unaudited pro forma adjusted consolidated net tangible assets
-- per Share" appendix table (HKEX news PDF), extracted by
-- agents/etl/silver/ingest_ipo_nav.py.
-- Consumed by GET /api/hkex/ipos and /api/hkex/ipos/subscription as
-- nav_per_share + offer_to_nav_pct.

ALTER TABLE silver.unified_ipo_calendar
    ADD COLUMN IF NOT EXISTS nav_per_share_hkd numeric,
    ADD COLUMN IF NOT EXISTS nav_asof date,
    ADD COLUMN IF NOT EXISTS nav_source text;

COMMENT ON COLUMN silver.unified_ipo_calendar.nav_per_share_hkd IS
    'Pro-forma adjusted net tangible assets per share in HKD from the prospectus, at the offer-price scenario matching fixed price or range mid.';
COMMENT ON COLUMN silver.unified_ipo_calendar.nav_asof IS
    'Balance-sheet date of the pro-forma NTA statement (e.g. 2026-06-30).';
COMMENT ON COLUMN silver.unified_ipo_calendar.nav_source IS
    'Provenance: prospectus PDF URL + page, or manual note.';
