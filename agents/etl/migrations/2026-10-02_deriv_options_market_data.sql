-- 2026-10-02 (goal deriv_options_schema_v1): Derivatives options market-data
-- schema — ThetaData probe + engine tables.
--
-- CONTAINMENT CONTRACT: NEW tables only. Nothing here alters or writes to any
-- existing bronze/silver/gold table. Scope is derivatives market data
-- (probe + engine), per authorised scope of derivatives_foundation_v1 Phase 1.
--
-- Vendor conventions captured 2026-10-02 from live ThetaData v3 API
-- (Theta Terminal 20260710, FREE tier) — see
-- workspace/deriv_options_schema_v1/SCHEMA.md for the full field mapping:
--   * strike: DOLLARS as JSON number, 3 decimals (650.000) — NOT scaled x1000
--   * right: 'CALL' / 'PUT' full words
--   * prices (bid/ask/OHLC): dollars
--   * timestamps: NAIVE America/New_York strings 'YYYY-MM-DDTHH:mm:ss.SSS'
--     (no offset); stored here as timestamptz interpreted in America/New_York
--   * EOD report generated 17:15 ET; quote = last NBBO at report generation;
--     `created` = report generation time, `last_trade` = last trade time
--   * open_interest reported ~06:30 ET and refers to the PREVIOUS trading
--     day's close (silver attributes it to that previous trade_date)
--   * missing values: vendor emits 0 / 0.0, never NULL
--
-- Tier gates measured 2026-10-02 (FREE key):
--   /option/history/eod           -> free, trailing ~1yr only (older = 403)
--   /stock/history/eod            -> free, trailing ~1yr only
--   /option/list/*                -> free, full metadata depth (2012+)
--   /option/history/open_interest -> 403, endpoint gated at VALUE
--   /option/history/greeks/eod    -> 403, endpoint gated at STANDARD
-- DDL below includes greeks/OI columns NOW so a tier upgrade needs no
-- migration — only a loader rerun.

BEGIN;

-- ============================================================================
-- 0) Append-only enforcement for bronze (shared trigger function)
-- ============================================================================
CREATE OR REPLACE FUNCTION bronze.reject_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'bronze tables are append-only: % not allowed on %', TG_OP, TG_TABLE_NAME;
END;
$$;
COMMENT ON FUNCTION bronze.reject_mutation() IS
    'Trigger function: rejects UPDATE/DELETE on append-only bronze raw tables. Reruns insert under a new ingest_run_id, never rewrite.';

-- ============================================================================
-- 1) bronze.thetadata_ingest_runs — one row per loader run (reconciliation
--    anchor: rows fetched vs bronze vs silver are compared per run)
-- ============================================================================
CREATE TABLE IF NOT EXISTS bronze.thetadata_ingest_runs (
    ingest_run_id   uuid        NOT NULL DEFAULT gen_random_uuid(),
    loader          text        NOT NULL,              -- e.g. 'thetadata_probe_pull.py'
    source_endpoint text        NOT NULL,              -- e.g. '/v3/option/history/eod'
    request_params  jsonb       NOT NULL,              -- symbol, date range, expiration, ...
    tier_at_ingest  text,                              -- vendor-reported subscription tier if known
    started_at      timestamptz NOT NULL DEFAULT now(),
    finished_at     timestamptz,
    status          text        NOT NULL DEFAULT 'RUNNING'
                    CHECK (status IN ('RUNNING','SUCCESS','PARTIAL','FAILED')),
    rows_fetched    integer,
    rows_inserted   integer,
    error           text,
    PRIMARY KEY (ingest_run_id)
);
COMMENT ON TABLE bronze.thetadata_ingest_runs IS
    'One row per ThetaData loader run. Reconciliation anchor: bronze/silver counts are grouped by ingest_run_id and compared against rows_fetched.';

-- ============================================================================
-- 2) bronze raw payload tables (append-only; parsed key columns duplicated
--    out of the payload for dedupe + query, payload itself untouched)
-- ============================================================================
CREATE TABLE IF NOT EXISTS bronze.thetadata_option_eod_raw (
    id             bigserial   NOT NULL,
    ingest_run_id  uuid        NOT NULL REFERENCES bronze.thetadata_ingest_runs(ingest_run_id),
    source_endpoint text       NOT NULL DEFAULT '/v3/option/history/eod',
    request_params jsonb       NOT NULL,
    symbol         text        NOT NULL,               -- as received, e.g. 'SPY'
    expiration     date        NOT NULL,
    strike         numeric(12,4) NOT NULL,             -- dollars, as received
    option_right   text        NOT NULL,               -- as received: 'CALL'/'PUT'
    trade_date     date        NOT NULL,               -- derived from request (EOD = 1 row/contract/day)
    payload        jsonb       NOT NULL,               -- full vendor record, untouched
    payload_hash   text        NOT NULL,               -- sha256 of canonical payload json
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (ingest_run_id, symbol, expiration, strike, option_right, trade_date)
);
CREATE INDEX IF NOT EXISTS thetadata_option_eod_raw_date_idx
    ON bronze.thetadata_option_eod_raw (symbol, trade_date);
COMMENT ON TABLE bronze.thetadata_option_eod_raw IS
    'Raw ThetaData /v3/option/history/eod payloads. Append-only; reruns insert under a new ingest_run_id.';

CREATE TABLE IF NOT EXISTS bronze.thetadata_option_greeks_eod_raw (
    id             bigserial   NOT NULL,
    ingest_run_id  uuid        NOT NULL REFERENCES bronze.thetadata_ingest_runs(ingest_run_id),
    source_endpoint text       NOT NULL DEFAULT '/v3/option/history/greeks/eod',
    request_params jsonb       NOT NULL,               -- incl. rate_type, rate_value, annual_dividend, greeks_version, underlyer_use_nbbo
    symbol         text        NOT NULL,
    expiration     date        NOT NULL,
    strike         numeric(12,4) NOT NULL,
    option_right   text        NOT NULL,
    trade_date     date        NOT NULL,
    payload        jsonb       NOT NULL,
    payload_hash   text        NOT NULL,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (ingest_run_id, symbol, expiration, strike, option_right, trade_date)
);
CREATE INDEX IF NOT EXISTS thetadata_option_greeks_eod_raw_date_idx
    ON bronze.thetadata_option_greeks_eod_raw (symbol, trade_date);
COMMENT ON TABLE bronze.thetadata_option_greeks_eod_raw IS
    'Raw ThetaData /v3/option/history/greeks/eod payloads (STANDARD tier). Append-only.';

CREATE TABLE IF NOT EXISTS bronze.thetadata_option_open_interest_raw (
    id             bigserial   NOT NULL,
    ingest_run_id  uuid        NOT NULL REFERENCES bronze.thetadata_ingest_runs(ingest_run_id),
    source_endpoint text       NOT NULL DEFAULT '/v3/option/history/open_interest',
    request_params jsonb       NOT NULL,
    symbol         text        NOT NULL,
    expiration     date        NOT NULL,
    strike         numeric(12,4) NOT NULL,
    option_right   text        NOT NULL,
    report_date    date        NOT NULL,               -- date of the 06:30 ET OPRA report
    payload        jsonb       NOT NULL,
    payload_hash   text        NOT NULL,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (ingest_run_id, symbol, expiration, strike, option_right, report_date)
);
CREATE INDEX IF NOT EXISTS thetadata_option_oi_raw_date_idx
    ON bronze.thetadata_option_open_interest_raw (symbol, report_date);
COMMENT ON TABLE bronze.thetadata_option_open_interest_raw IS
    'Raw ThetaData /v3/option/history/open_interest payloads (VALUE tier). OI at ~06:30 ET refers to PREVIOUS trading day close. Append-only.';

CREATE TABLE IF NOT EXISTS bronze.thetadata_stock_eod_raw (
    id             bigserial   NOT NULL,
    ingest_run_id  uuid        NOT NULL REFERENCES bronze.thetadata_ingest_runs(ingest_run_id),
    source_endpoint text       NOT NULL DEFAULT '/v3/stock/history/eod',
    request_params jsonb       NOT NULL,
    symbol         text        NOT NULL,
    trade_date     date        NOT NULL,
    payload        jsonb       NOT NULL,
    payload_hash   text        NOT NULL,
    ingested_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (id),
    UNIQUE (ingest_run_id, symbol, trade_date)
);
COMMENT ON TABLE bronze.thetadata_stock_eod_raw IS
    'Raw ThetaData /v3/stock/history/eod payloads (underlying close for greeks/marks). Append-only.';

-- Append-only triggers
DROP TRIGGER IF EXISTS reject_mutation ON bronze.thetadata_option_eod_raw;
CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON bronze.thetadata_option_eod_raw
    FOR EACH ROW EXECUTE FUNCTION bronze.reject_mutation();
DROP TRIGGER IF EXISTS reject_mutation ON bronze.thetadata_option_greeks_eod_raw;
CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON bronze.thetadata_option_greeks_eod_raw
    FOR EACH ROW EXECUTE FUNCTION bronze.reject_mutation();
DROP TRIGGER IF EXISTS reject_mutation ON bronze.thetadata_option_open_interest_raw;
CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON bronze.thetadata_option_open_interest_raw
    FOR EACH ROW EXECUTE FUNCTION bronze.reject_mutation();
DROP TRIGGER IF EXISTS reject_mutation ON bronze.thetadata_stock_eod_raw;
CREATE TRIGGER reject_mutation BEFORE UPDATE OR DELETE ON bronze.thetadata_stock_eod_raw
    FOR EACH ROW EXECUTE FUNCTION bronze.reject_mutation();

-- ============================================================================
-- 3) silver.option_contracts — dimension, one row per contract ever seen.
--    occ_symbol is the natural key. ThetaData v3 does NOT return OCC
--    symbology; we derive it per OCC/OPRA convention:
--    root padded to 6 + yymmdd + C/P + strike*1000 zero-padded to 8
--    ('SPY   260918C00650000'). Derivation documented in SCHEMA.md.
-- ============================================================================
CREATE TABLE IF NOT EXISTS silver.option_contracts (
    contract_id    bigserial    NOT NULL,
    occ_symbol     varchar(21)  NOT NULL,              -- OCC symbology, derived
    underlying     text         NOT NULL,
    expiry         date         NOT NULL,
    strike         numeric(12,4) NOT NULL,             -- dollars, normalised
    option_right   char(1)      NOT NULL CHECK (option_right IN ('C','P')),
    multiplier     integer      NOT NULL DEFAULT 100,
    exercise_style text         NOT NULL CHECK (exercise_style IN ('AMERICAN','EUROPEAN')),
    settlement     text         NOT NULL DEFAULT 'PHYSICAL' CHECK (settlement IN ('PHYSICAL','CASH')),
    first_seen     date         NOT NULL,
    last_seen      date         NOT NULL,
    created_at     timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_id),
    UNIQUE (occ_symbol),
    UNIQUE (underlying, expiry, strike, option_right)  -- natural identity backup
);
COMMENT ON TABLE silver.option_contracts IS
    'Option contract dimension. occ_symbol derived (vendor does not supply it). exercise_style/settlement explicit per underlying, never assumed.';

-- ============================================================================
-- 4) silver.option_eod_quotes — one row per contract per trade_date.
--    Rows failing quality checks STAY in the table with quality_flags set;
--    the engine decides to skip. evidence_class = QUOTED_CHAIN (gate D10).
-- ============================================================================
CREATE TABLE IF NOT EXISTS silver.option_eod_quotes (
    contract_id      bigint       NOT NULL REFERENCES silver.option_contracts(contract_id),
    trade_date       date         NOT NULL,
    bid              numeric(14,6),
    ask              numeric(14,6),
    mid              numeric(14,6),                   -- computed (bid+ask)/2, labelled here
    bid_size         integer,
    ask_size         integer,
    volume           bigint,
    trade_count      integer,
    open_interest    bigint,                          -- NULL until VALUE tier pull lands
    underlying_close numeric(14,6),
    last_trade_at    timestamptz,                     -- naive ET converted with America/New_York
    report_created_at timestamptz,                    -- vendor `created` (17:15 ET report generation)
    quality_flags    text[]       NOT NULL DEFAULT '{}',  -- ZERO_BID, WIDE_SPREAD, STALE_OI, CROSSED, NO_TRADES
    evidence_class   text         NOT NULL DEFAULT 'QUOTED_CHAIN' CHECK (evidence_class = 'QUOTED_CHAIN'),
    ingest_run_id    uuid         NOT NULL REFERENCES bronze.thetadata_ingest_runs(ingest_run_id),
    created_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_id, trade_date)
);
CREATE INDEX IF NOT EXISTS option_eod_quotes_date_idx
    ON silver.option_eod_quotes (trade_date);
COMMENT ON TABLE silver.option_eod_quotes IS
    'Normalised EOD NBBO quotes per contract/day. mid is computed here (only place it is computed). quality_flagged rows are kept, never dropped. evidence_class=QUOTED_CHAIN satisfies gate D10.';

-- ============================================================================
-- 5) silver.option_eod_greeks — one row per contract per trade_date.
--    greek_source: VENDOR (ThetaData STANDARD tier) or COMPUTED (our model).
--    model_params records the exact model inputs used so VENDOR and COMPUTED
--    rows are never ambiguous (rate/dividend assumptions travel with the row).
-- ============================================================================
CREATE TABLE IF NOT EXISTS silver.option_eod_greeks (
    contract_id    bigint       NOT NULL REFERENCES silver.option_contracts(contract_id),
    trade_date     date         NOT NULL,
    implied_vol    numeric(12,6),
    delta          numeric(12,6),
    gamma          numeric(12,6),
    theta          numeric(14,6),
    vega           numeric(14,6),
    rho            numeric(14,6),
    iv_error       numeric(14,8),
    underlying_price numeric(14,6),                   -- vendor underlying ref used for the calc
    greek_source   text         NOT NULL CHECK (greek_source IN ('VENDOR','COMPUTED')),
    model_params   jsonb        NOT NULL DEFAULT '{}',  -- rate_type, rate_value, annual_dividend, greeks_version, underlyer_use_nbbo
    ingest_run_id  uuid         NOT NULL REFERENCES bronze.thetadata_ingest_runs(ingest_run_id),
    created_at     timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (contract_id, trade_date)
);
CREATE INDEX IF NOT EXISTS option_eod_greeks_date_idx
    ON silver.option_eod_greeks (trade_date);
COMMENT ON TABLE silver.option_eod_greeks IS
    'EOD IV + first-order greeks per contract/day. greek_source VENDOR vs COMPUTED is explicit; model_params carries the exact rate/dividend/version assumptions.';

-- ============================================================================
-- 6) gold.option_vol_features_daily — DDL ONLY, no population in Phase 1.
--    available_after is the lookahead firewall: a strategy may only use a
--    feature row when signal_date >= available_after. VRP and any
--    forward-looking aggregate get available_after = feature_date + horizon.
-- ============================================================================
CREATE TABLE IF NOT EXISTS gold.option_vol_features_daily (
    underlying        text        NOT NULL,
    feature_date      date        NOT NULL,
    atm_iv_30d        numeric(12,6),
    atm_iv_60d        numeric(12,6),
    atm_iv_90d        numeric(12,6),
    iv_term_slope     numeric(12,6),                  -- atm_iv_60d - atm_iv_30d
    iv_rank_1y        numeric(8,4),                   -- vs trailing 252d
    iv_pctile_1y      numeric(8,4),
    skew_25d_30d      numeric(12,6),                  -- IV(25d put) - IV(25d call), 30D const maturity
    rv_20d            numeric(12,6),
    rv_60d            numeric(12,6),
    vrp_30d           numeric(12,6),                  -- atm_iv_30d - subsequent 30d RV; lagged
    event_implied_move numeric(12,6),
    regime            text,                           -- convenience join from gold.regime_label
    vix_z60           numeric(12,6),                  -- convenience join from gold.regime_features
    available_after   date        NOT NULL,           -- lookahead firewall
    computed_at       timestamptz NOT NULL DEFAULT now(),
    source_run_id     uuid,                           -- feature-computation run (not ingest run)
    PRIMARY KEY (underlying, feature_date)
);
COMMENT ON TABLE gold.option_vol_features_daily IS
    'Gold vol features per underlying/day. DDL only in Phase 1 (no population). available_after = first date a strategy may use the row (lookahead firewall).';

COMMIT;

-- Acceptance verification
SELECT table_schema, table_name FROM information_schema.tables
WHERE (table_schema = 'bronze' AND table_name LIKE 'thetadata_%')
   OR (table_schema = 'silver' AND table_name IN ('option_contracts','option_eod_quotes','option_eod_greeks'))
   OR (table_schema = 'gold'   AND table_name = 'option_vol_features_daily')
ORDER BY table_schema, table_name;
