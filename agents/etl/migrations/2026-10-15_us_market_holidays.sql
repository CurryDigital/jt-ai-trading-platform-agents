-- 2026-10-15 (kanban t_183d8bb1): NYSE full-close holiday reference table.
-- Purpose: trading-calendar guard for gold.daily_ohlcv writers (gold_builder
-- build_daily_ohlcv) so yfinance weekend/holiday artifact rows can never
-- re-enter gold and corrupt rolling features (regime_features adx14 NaN
-- recurrence of 2026-04-16/04-23/05-29/06-09/06-11).
-- Only full NYSE closes are listed (early closes like Black Friday 13:00 ET
-- are trading days and intentionally absent).

CREATE TABLE IF NOT EXISTS gold.us_market_holidays (
    holiday_date date PRIMARY KEY,
    name         text NOT NULL
);

INSERT INTO gold.us_market_holidays (holiday_date, name) VALUES
 ('2019-01-01','New Year''s Day'),('2019-01-21','MLK Day'),('2019-02-18','Presidents Day'),('2019-04-19','Good Friday'),('2019-05-27','Memorial Day'),('2019-07-04','Independence Day'),('2019-09-02','Labor Day'),('2019-11-28','Thanksgiving'),('2019-12-25','Christmas'),
 ('2020-01-01','New Year''s Day'),('2020-01-20','MLK Day'),('2020-02-17','Presidents Day'),('2020-04-10','Good Friday'),('2020-05-25','Memorial Day'),('2020-07-03','Independence Day (obs)'),('2020-09-07','Labor Day'),('2020-11-26','Thanksgiving'),('2020-12-25','Christmas'),
 ('2021-01-01','New Year''s Day'),('2021-01-18','MLK Day'),('2021-02-15','Presidents Day'),('2021-04-02','Good Friday'),('2021-05-31','Memorial Day'),('2021-07-05','Independence Day (obs)'),('2021-09-06','Labor Day'),('2021-11-25','Thanksgiving'),('2021-12-24','Christmas (obs)'),
 ('2022-01-17','MLK Day'),('2022-02-21','Presidents Day'),('2022-04-15','Good Friday'),('2022-05-30','Memorial Day'),('2022-06-20','Juneteenth (obs)'),('2022-07-04','Independence Day'),('2022-09-05','Labor Day'),('2022-11-24','Thanksgiving'),('2022-12-26','Christmas (obs)'),
 ('2023-01-02','New Year''s Day (obs)'),('2023-01-16','MLK Day'),('2023-02-20','Presidents Day'),('2023-04-07','Good Friday'),('2023-05-29','Memorial Day'),('2023-06-19','Juneteenth'),('2023-07-04','Independence Day'),('2023-09-04','Labor Day'),('2023-11-23','Thanksgiving'),('2023-12-25','Christmas'),
 ('2024-01-01','New Year''s Day'),('2024-01-15','MLK Day'),('2024-02-19','Presidents Day'),('2024-03-29','Good Friday'),('2024-05-27','Memorial Day'),('2024-06-19','Juneteenth'),('2024-07-04','Independence Day'),('2024-09-02','Labor Day'),('2024-11-28','Thanksgiving'),('2024-12-25','Christmas'),
 ('2025-01-01','New Year''s Day'),('2025-01-20','MLK Day'),('2025-02-17','Presidents Day'),('2025-04-18','Good Friday'),('2025-05-26','Memorial Day'),('2025-06-19','Juneteenth'),('2025-07-04','Independence Day'),('2025-09-01','Labor Day'),('2025-11-27','Thanksgiving'),('2025-12-25','Christmas'),
 ('2026-01-01','New Year''s Day'),('2026-01-19','MLK Day'),('2026-02-16','Presidents Day'),('2026-04-03','Good Friday'),('2026-05-25','Memorial Day'),('2026-06-19','Juneteenth'),('2026-07-03','Independence Day (obs)'),('2026-09-07','Labor Day'),('2026-11-26','Thanksgiving'),('2026-12-25','Christmas'),
 ('2027-01-01','New Year''s Day'),('2027-01-18','MLK Day'),('2027-02-15','Presidents Day'),('2027-03-26','Good Friday'),('2027-05-31','Memorial Day'),('2027-06-18','Juneteenth (obs)'),('2027-07-05','Independence Day (obs)'),('2027-09-06','Labor Day'),('2027-11-25','Thanksgiving'),('2027-12-24','Christmas (obs)'),
 ('2028-01-17','MLK Day'),('2028-02-21','Presidents Day'),('2028-04-14','Good Friday'),('2028-05-29','Memorial Day'),('2028-06-19','Juneteenth'),('2028-07-04','Independence Day'),('2028-09-04','Labor Day'),('2028-11-23','Thanksgiving'),('2028-12-25','Christmas'),
 ('2029-01-01','New Year''s Day'),('2029-01-15','MLK Day'),('2029-02-19','Presidents Day'),('2029-03-30','Good Friday'),('2029-05-28','Memorial Day'),('2029-06-19','Juneteenth'),('2029-07-04','Independence Day'),('2029-09-03','Labor Day'),('2029-11-22','Thanksgiving'),('2029-12-25','Christmas'),
 ('2030-01-01','New Year''s Day'),('2030-01-21','MLK Day'),('2030-02-18','Presidents Day'),('2030-03-29','Good Friday'),('2030-05-27','Memorial Day'),('2030-06-19','Juneteenth'),('2030-07-04','Independence Day'),('2030-09-02','Labor Day'),('2030-11-28','Thanksgiving'),('2030-12-25','Christmas')
ON CONFLICT (holiday_date) DO NOTHING;
