-- 2026-09-02: stock_name_zh (Chinese company name) on HK IPO calendar
-- kanban t_437922f4. IPO tab Name column renders Chinese name.
-- API /api/hkex/ipos self-adapts once column exists on gold.hk_ipo_calendar.

ALTER TABLE gold.hk_ipo_calendar
    ADD COLUMN IF NOT EXISTS stock_name_zh varchar;

ALTER TABLE silver.unified_ipo_calendar
    ADD COLUMN IF NOT EXISTS stock_name_zh varchar;

COMMENT ON COLUMN gold.hk_ipo_calendar.stock_name_zh IS
    'Chinese company name (繁體中文) from HKEX List of Securities / prospectus cover / AAStocks TC';
COMMENT ON COLUMN silver.unified_ipo_calendar.stock_name_zh IS
    'Chinese company name (繁體中文) from HKEX List of Securities / prospectus cover / AAStocks TC';
