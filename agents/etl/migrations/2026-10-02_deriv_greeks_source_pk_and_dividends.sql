-- 2026-10-02_deriv_greeks_source_pk_and_dividends.sql
-- Scope: derivatives tables only.
-- 1) silver.option_eod_greeks: allow VENDOR and COMPUTED greeks to coexist for
--    the same contract-day (paid-month cross-check requires both). Old PK
--    (contract_id, trade_date) silently shadowed one source with the other.
-- 2) deriv.underlying_dividends: discrete cash dividends used by the in-house
--    American pricer (escrowed-dividend CRR). Provenance per row.

BEGIN;

ALTER TABLE silver.option_eod_greeks
    DROP CONSTRAINT IF EXISTS option_eod_greeks_pkey;
ALTER TABLE silver.option_eod_greeks
    ADD CONSTRAINT option_eod_greeks_pkey
    PRIMARY KEY (contract_id, trade_date, greek_source);

CREATE TABLE IF NOT EXISTS deriv.underlying_dividends (
    underlying  text            NOT NULL,
    ex_date     date            NOT NULL,
    amount      numeric(12,6)   NOT NULL CHECK (amount > 0),
    source      text            NOT NULL,   -- e.g. YAHOO_CHART_API
    fetched_at  timestamptz     NOT NULL DEFAULT now(),
    PRIMARY KEY (underlying, ex_date, source)
);

COMMIT;
