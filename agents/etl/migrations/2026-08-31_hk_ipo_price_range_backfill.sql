-- 2026-08-31_hk_ipo_price_range_backfill.sql
-- Task t_4ac22423: indicative offer price range for HK IPOs (S3 discount-reversal signal).
-- Populated by silver/backfill_ipo_price_range.py + silver/ipo_price_range_core.py
-- from HKEXnews prospectus PDFs. offer_price_low/offer_price_high columns pre-existed
-- (AAStocks listed-IPO scrape); this migration adds the audit table and provenance columns.

create table if not exists bronze.hkex_ipo_price_range_raw (
  ticker_code text not null,
  listing_date date not null,
  status text not null,           -- ok | ok_mktcap | fixed | max_only | no_stock_id | no_offer_* | docs_purged | parse_fail | error
  low numeric, high numeric, fixed numeric,
  doc_url text, snippet text, error text,
  stock_id text, n_docs int,
  attempted_at timestamptz default now(),
  primary key (ticker_code, listing_date)
);

alter table silver.unified_ipo_calendar
  add column if not exists price_range_source text,   -- hkexnews_prospectus | hkexnews_prospectus_mktcap_table | hkexnews_prospectus_max_only | hkexnews_unavailable[_delisted] | no_offer_event_{transfer,introduction,other,despac}
  add column if not exists fixed_price boolean;       -- true = single fixed offer price (range NULL by design)

-- Semantics for qr_research (S3 discount_reversal):
--   range_mid  = (offer_price_low + offer_price_high) / 2, valid when both NOT NULL
--   fixed_price=true rows: no range exists; exclude or use offer_price directly.
--   max_only rows: only offer_price_high (2025+ A+H practice: cover states cap only).
