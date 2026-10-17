-- gold.exchange_holidays: per-market holiday calendars with observed/in-lieu
-- dates (user directive 2026-10-17, phantom-cleanup follow-up 1).
-- Source CSVs: workspace/exchange_calendars/{sgx,hkex,china}_holidays_2018_2026.csv
-- (compiled 2026-10-17, see notes.md there). Rows are CLOSED WEEKDAYS only;
-- weekends are implied. 'observed' flag marks in-lieu closures (e.g. Vesak
-- 2026 fell Sunday 05-31, SGX closed Monday 06-01).
CREATE TABLE IF NOT EXISTS gold.exchange_holidays (
    market        text NOT NULL,   -- 'SG' | 'HK' | 'CN' | 'US'
    holiday_date  date NOT NULL,
    name          text NOT NULL,
    observed      boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (market, holiday_date)
);

-- Seed the confirmed anchor immediately (validated against two sources):
INSERT INTO gold.exchange_holidays (market, holiday_date, name, observed)
VALUES ('SG', DATE '2026-06-01', 'Vesak Day (observed — Vesak fell Sun 2026-05-31)', true)
ON CONFLICT DO NOTHING;
