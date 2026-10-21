-- 2026-10-09_fx_currency_labeling.sql
-- Kanban t_65d96f4a (P2 FX FIX): currency-labeled account tables + shared conversion layer.
--
-- DUP825942 base currency is HKD. Historically HKD account values were stored in
-- USD-assumed columns with no currency marker. This migration:
--   1. creates gold.fx_rates (daily dated FX rates; the ONLY rate source)
--   2. creates bronze.ibkr_account_values (raw per-tag-per-currency rows)
--   3. creates bronze.ibkr_fx_rates (raw ExchangeRate captures)
--   4. adds currency + USD-converted columns (with fx_rate/fx_date provenance)
--      to bronze/gold.ibkr_account_summary, gold.account_nav_daily,
--      gold.portfolio_snapshots
--   5. tags EXISTING history by currency (append-only: values NOT rewritten)
--
-- Column semantics (contract for all readers):
--   ibkr_account_summary.net_liquidation / available_funds / buying_power
--       = BASE currency of the account (HKD for DUP825942), see base_currency col.
--   *_usd columns = value * fx_rate, where fx_rate = USD per 1 unit of base ccy,
--       as of fx_date, sourced from gold.fx_rates.
--   gold.fx_rates.rate: 1 from_ccy = rate to_ccy (e.g. USD->HKD @ 7.846).
--   account_nav_daily.equity = native currency of the book (see currency col);
--       equity_usd = converted. Existing rows tagged, not rewritten.
--   portfolio_snapshots.total_value/cash_value/positions_value = native ccy of
--       the book (see currency col); *_usd columns converted. gross_exposure /
--       net_exposure / daily_pnl were ALWAYS contract-currency (USD for the US
--       book) and are now also mirrored into *_usd with that fact made explicit.

BEGIN;

-- ── 1. gold.fx_rates: the single FX rate source ─────────────────────────────
CREATE TABLE IF NOT EXISTS gold.fx_rates (
    from_ccy   varchar(8)  NOT NULL,
    to_ccy     varchar(8)  NOT NULL,
    rate       numeric     NOT NULL CHECK (rate > 0),
    as_of_date date        NOT NULL,
    source     varchar(32) NOT NULL,           -- e.g. 'ibkr_account_summary'
    fetched_at timestamp   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (from_ccy, to_ccy, as_of_date)
);

-- ── 2. bronze raw per-tag-per-currency account values ───────────────────────
CREATE TABLE IF NOT EXISTS bronze.ibkr_account_values (
    account    varchar(32) NOT NULL,
    tag        varchar(64) NOT NULL,
    currency   varchar(8)  NOT NULL,           -- 'BASE', 'HKD', 'USD', ...
    value      numeric,
    fetched_at timestamp   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account, tag, currency)
);

-- ── 3. bronze raw FX captures (ExchangeRate tag) ────────────────────────────
CREATE TABLE IF NOT EXISTS bronze.ibkr_fx_rates (
    account    varchar(32) NOT NULL,
    from_ccy   varchar(8)  NOT NULL,           -- currency of the ExchangeRate row
    to_ccy     varchar(8)  NOT NULL,           -- account base currency
    rate       numeric     NOT NULL,           -- 1 from_ccy = rate to_ccy
    fetched_at timestamp   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (account, from_ccy, to_ccy)
);

-- ── 4a. account summary tables: currency labels + USD columns ───────────────
ALTER TABLE bronze.ibkr_account_summary
    ADD COLUMN IF NOT EXISTS base_currency       varchar(8),
    ADD COLUMN IF NOT EXISTS net_liquidation_usd numeric,
    ADD COLUMN IF NOT EXISTS available_funds_usd numeric,
    ADD COLUMN IF NOT EXISTS buying_power_usd    numeric,
    ADD COLUMN IF NOT EXISTS cash_total_usd      numeric,
    ADD COLUMN IF NOT EXISTS fx_rate             numeric,  -- USD per 1 base unit
    ADD COLUMN IF NOT EXISTS fx_date             date;

ALTER TABLE gold.ibkr_account_summary
    ADD COLUMN IF NOT EXISTS base_currency       varchar(8),
    ADD COLUMN IF NOT EXISTS net_liquidation_usd numeric,
    ADD COLUMN IF NOT EXISTS available_funds_usd numeric,
    ADD COLUMN IF NOT EXISTS buying_power_usd    numeric,
    ADD COLUMN IF NOT EXISTS cash_total_usd      numeric,
    ADD COLUMN IF NOT EXISTS fx_rate             numeric,
    ADD COLUMN IF NOT EXISTS fx_date             date;

-- ── 4b. gold.account_nav_daily: tag history, add converted columns ──────────
ALTER TABLE gold.account_nav_daily
    ADD COLUMN IF NOT EXISTS currency   varchar(8),
    ADD COLUMN IF NOT EXISTS equity_usd numeric,
    ADD COLUMN IF NOT EXISTS fx_rate    numeric,
    ADD COLUMN IF NOT EXISTS fx_date    date;

-- Append-only tagging of existing rows (values NOT rewritten):
--   live book  = IBKR DUP825942 -> HKD
--   paper book = SIM ledger     -> USD
UPDATE gold.account_nav_daily SET currency = 'HKD' WHERE book = 'live'  AND currency IS NULL;
UPDATE gold.account_nav_daily SET currency = 'USD' WHERE book = 'paper' AND currency IS NULL;

-- ── 4c. gold.portfolio_snapshots: tag history, add converted columns ────────
ALTER TABLE gold.portfolio_snapshots
    ADD COLUMN IF NOT EXISTS currency            varchar(8),
    ADD COLUMN IF NOT EXISTS total_value_usd     numeric,
    ADD COLUMN IF NOT EXISTS cash_value_usd      numeric,
    ADD COLUMN IF NOT EXISTS positions_value_usd numeric,
    ADD COLUMN IF NOT EXISTS gross_exposure_usd  numeric,
    ADD COLUMN IF NOT EXISTS net_exposure_usd    numeric,
    ADD COLUMN IF NOT EXISTS var_95_usd          numeric,
    ADD COLUMN IF NOT EXISTS fx_rate             numeric,
    ADD COLUMN IF NOT EXISTS fx_date             date;

-- Existing 'live' + account-id rows hold HKD account values (USD exposures);
-- 'paper' rows (if any) are USD. One '' row (2026-05-14) left NULL = unknown.
UPDATE gold.portfolio_snapshots SET currency = 'HKD'
    WHERE portfolio_type IN ('live', 'DUP825942') AND currency IS NULL;
UPDATE gold.portfolio_snapshots SET currency = 'USD'
    WHERE portfolio_type = 'paper' AND currency IS NULL;

COMMIT;
