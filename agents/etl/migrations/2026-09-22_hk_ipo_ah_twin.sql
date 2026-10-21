-- Migration: A+H twin mapping on silver.unified_ipo_calendar (kanban t_5d325908)
-- a_twin_ticker: DB convention .SS/.SZ (yfinance-compatible)
-- a_twin_status: 'mapped' | 'no_a_twin' (H-share-only issuer, no A-share listing exists)
-- a_twin_source: 'etnet_ah' | 'eastmoney_suggest+f10_verify'
ALTER TABLE silver.unified_ipo_calendar
    ADD COLUMN IF NOT EXISTS a_twin_ticker  varchar(16),
    ADD COLUMN IF NOT EXISTS a_twin_status  varchar(16),
    ADD COLUMN IF NOT EXISTS a_twin_source  varchar(40);
CREATE INDEX IF NOT EXISTS idx_unified_ipo_calendar_a_twin
    ON silver.unified_ipo_calendar (a_twin_ticker) WHERE a_twin_ticker IS NOT NULL;
