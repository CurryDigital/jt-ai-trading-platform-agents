-- 018_macro_calendar.sql
-- Kanban t_7a646947: global macro catalyst calendar (US CPI, Payrolls, FOMC,
-- ECB, RBA, BOJ, PBoC LPR, HK GDP/CPI) with ISO dates + source provenance.
--
-- Successor to gold.economic_calendar (which holds 3 legacy HK rows with
-- year-less varchar dates). The legacy table/view consumption.macro_events
-- stay untouched for /api/macro/regions until the frontend migrates.
--
-- Refresh: agents/etl/gold/market/build_macro_calendar.py (weekly cron
-- qr_etl.macro_calendar_refresh). Upsert-only; rows are never deleted so a
-- source outage can never wipe the calendar.

CREATE TABLE IF NOT EXISTS gold.macro_calendar (
    id          BIGSERIAL PRIMARY KEY,
    region      VARCHAR(8)   NOT NULL,          -- US, EZ, AU, JP, CN, HK
    event       VARCHAR(160) NOT NULL,          -- 'US CPI (Jul 2026)', 'FOMC Rate Decision', ...
    event_date  DATE         NOT NULL,          -- ISO YYYY-MM-DD
    importance  VARCHAR(8)   NOT NULL,          -- High | Med | Low
    source      VARCHAR(120) NOT NULL,          -- authoritative source label
    source_url  TEXT,
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT macro_calendar_natural_key UNIQUE (region, event, event_date)
);

CREATE INDEX IF NOT EXISTS macro_calendar_date_idx
    ON gold.macro_calendar (event_date);

COMMENT ON TABLE gold.macro_calendar IS
    'Forward + trailing global macro catalyst schedule. Populated by '
    'build_macro_calendar.py from official published calendars (BLS, Fed, '
    'ECB, RBA, BOJ, HK C&SD) plus the PBoC LPR fixing rule. Upsert-only, '
    'weekly refresh. Every row carries its source + URL.';

-- Consumption view served by GET /api/macro/calendar.
CREATE OR REPLACE VIEW consumption.macro_calendar AS
SELECT region,
       event,
       event_date,
       importance,
       source,
       updated_at
FROM gold.macro_calendar
ORDER BY event_date, region;
