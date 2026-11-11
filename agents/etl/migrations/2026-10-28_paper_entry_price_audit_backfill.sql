-- 2026-10-28: append-only audit + correction ledger for backfill-era (stamped 2026-08-05)
-- paper entry prices (kanban t_baf767e2). Never rewrites gold.paper_trades_synthetic.entry_price.
-- Pattern follows 2026-10-26_unified_prices_pit_audit.sql (append-only + guard triggers).

CREATE TABLE IF NOT EXISTS gold.paper_trade_entry_price_audit (
    audit_id              bigserial PRIMARY KEY,
    trade_id              integer NOT NULL REFERENCES gold.paper_trades_synthetic(id),
    strategy_id           text    NOT NULL,
    ticker                text    NOT NULL,
    stamped_entry_date    date    NOT NULL,
    ledger_entry_price    numeric NOT NULL,
    source_date           date,                    -- declared entry_price_source_date (NULL = LEGACY)
    entry_price_basis     text,
    stamped_close         numeric,                 -- silver.unified_prices close on stamped_entry_date
    source_close          numeric,                 -- silver.unified_prices close on source_date
    dev_vs_stamped_pct    numeric,                 -- (ledger - stamped_close)/stamped_close * 100
    dev_vs_source_pct     numeric,
    vintage_date          date,                    -- true vintage (declared source or best-match date)
    classification        text    NOT NULL,        -- MATCH_SOURCE | MATCH_ENTRY | MATCH_NEITHER
    action                text    NOT NULL,        -- CORRECT | FLAG | OK
    flag_reason           text,                    -- STALE_VINTAGE | RESTATEMENT_DRIFT | LEGACY_NO_SOURCE | CONVENTION
    corrected_entry_price numeric,                 -- stamped-date close when action='CORRECT'
    status_at_audit       text,
    task_id               text    NOT NULL DEFAULT 't_baf767e2',
    audited_at            timestamptz NOT NULL DEFAULT now()
);

-- Append-only guards: reject UPDATE / DELETE / TRUNCATE
CREATE OR REPLACE FUNCTION gold.paper_entry_audit_no_update() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'gold.paper_trade_entry_price_audit is append-only (UPDATE rejected)';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION gold.paper_entry_audit_no_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'gold.paper_trade_entry_price_audit is append-only (DELETE rejected)';
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION gold.paper_entry_audit_no_truncate() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'gold.paper_trade_entry_price_audit is append-only (TRUNCATE rejected)';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_paper_entry_audit_no_update ON gold.paper_trade_entry_price_audit;
CREATE TRIGGER trg_paper_entry_audit_no_update
    BEFORE UPDATE ON gold.paper_trade_entry_price_audit
    FOR EACH ROW EXECUTE FUNCTION gold.paper_entry_audit_no_update();

DROP TRIGGER IF EXISTS trg_paper_entry_audit_no_delete ON gold.paper_trade_entry_price_audit;
CREATE TRIGGER trg_paper_entry_audit_no_delete
    BEFORE DELETE ON gold.paper_trade_entry_price_audit
    FOR EACH ROW EXECUTE FUNCTION gold.paper_entry_audit_no_delete();

DROP TRIGGER IF EXISTS trg_paper_entry_audit_no_truncate ON gold.paper_trade_entry_price_audit;
CREATE TRIGGER trg_paper_entry_audit_no_truncate
    BEFORE TRUNCATE ON gold.paper_trade_entry_price_audit
    FOR EACH STATEMENT EXECUTE FUNCTION gold.paper_entry_audit_no_truncate();

CREATE INDEX IF NOT EXISTS idx_paper_entry_audit_trade ON gold.paper_trade_entry_price_audit(trade_id);
CREATE INDEX IF NOT EXISTS idx_paper_entry_audit_strategy ON gold.paper_trade_entry_price_audit(strategy_id, stamped_entry_date);
