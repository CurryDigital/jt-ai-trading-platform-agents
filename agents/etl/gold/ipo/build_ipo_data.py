# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold IPO: HK IPO Calendar, Details & Performance
Reads from: silver.unified_ipo_calendar, silver.unified_ipo_performance,
            bronze.hkex_ipo_prospectus_raw
Writes to:  gold.hk_ipo_calendar, gold.hk_ipo_details, gold.hk_ipo_performance
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_CALENDAR = """
-- gold.hk_ipo_calendar stays keyed on ticker (frontend convention); recycled
-- tickers (12 in silver) map to their LATEST listing here.
INSERT INTO gold.hk_ipo_calendar
  (ticker, stock_name, stock_name_zh, listing_date, offer_price, currency,
   market_cap_hkd, market_cap_usd, sector, sub_sector,
   sponsor, underwriters, shares_offered, greenshoe_shares,
   board, is_active, updated_at)
SELECT
  ticker, stock_name, stock_name_zh, listing_date, offer_price, currency,
  market_cap_hkd, market_cap_usd, sector, sub_sector,
  sponsor, underwriters, shares_offered, greenshoe_shares,
  'MAIN' AS board, TRUE AS is_active, NOW()
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY listing_date DESC) rn
  FROM silver.unified_ipo_calendar
) c
WHERE rn = 1
ON CONFLICT (ticker) DO UPDATE SET
  listing_date    = EXCLUDED.listing_date,
  -- 2026-09-02 (t_437922f4): recycled tickers (e.g. 0625 RREEF->SHEIN) must
  -- not keep the previous listing's name; name follows the newest listing.
  stock_name      = CASE
                      WHEN EXCLUDED.listing_date >= hk_ipo_calendar.listing_date
                        THEN COALESCE(EXCLUDED.stock_name, hk_ipo_calendar.stock_name)
                      ELSE hk_ipo_calendar.stock_name
                    END,
  market_cap_hkd  = EXCLUDED.market_cap_hkd,
  -- 2026-09-02 (t_437922f4): propagate Chinese names from silver; never
  -- overwrite an existing gold name with NULL.
  stock_name_zh   = COALESCE(EXCLUDED.stock_name_zh, hk_ipo_calendar.stock_name_zh),
  -- 2026-09-02 (t_2f98c3be): propagate sector backfills from silver; never
  -- overwrite an existing gold sector with NULL.
  -- 2026-09-26 (t_467af8d2): offer_price was insert-only, so rows first
  -- inserted during the subscription window (price not yet fixed) stayed
  -- NULL in gold forever even after silver landed the final price.
  -- Propagate from silver; never wipe an existing value with NULL.
  offer_price     = COALESCE(EXCLUDED.offer_price, hk_ipo_calendar.offer_price),
  sector          = COALESCE(EXCLUDED.sector, hk_ipo_calendar.sector),
  sub_sector      = COALESCE(EXCLUDED.sub_sector, hk_ipo_calendar.sub_sector),
  is_active       = EXCLUDED.is_active,
  updated_at      = NOW();
"""

SQL_DETAILS = """
INSERT INTO gold.hk_ipo_details
  (ticker, oversubscription_retail, oversubscription_institutional,
   oversubscription_total, cornerstone_total_pct, cornerstone_investors,
   lockup_period_days, greenshoe_pct, listing_date,
   application_start, application_end, allotment_date, updated_at)
SELECT
  c.ticker,
  c.oversubscription_retail,
  c.oversubscription_institutional,
  c.oversubscription_retail + COALESCE(c.oversubscription_institutional, 0) AS oversubscription_total,
  c.cornerstone_total_pct,
  NULL AS cornerstone_investors,
  c.lockup_period_days,
  c.greenshoe_pct,
  c.listing_date,
  c.application_start,
  c.application_end,
  c.allotment_date,
  NOW()
FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY listing_date DESC) rn
  FROM silver.unified_ipo_calendar
) c
WHERE rn = 1
ON CONFLICT (ticker) DO UPDATE SET
  oversubscription_retail        = EXCLUDED.oversubscription_retail,
  oversubscription_institutional = EXCLUDED.oversubscription_institutional,
  -- 2026-09-02 (t_e71cffde): subscription-window feed (AAStocks upcoming).
  -- Never wipe a populated window with NULL (upcoming rows rotate out of the
  -- feed once listed); only overwrite with real values.
  application_start = COALESCE(EXCLUDED.application_start, hk_ipo_details.application_start),
  application_end   = COALESCE(EXCLUDED.application_end, hk_ipo_details.application_end),
  allotment_date    = COALESCE(EXCLUDED.allotment_date, hk_ipo_details.allotment_date),
  updated_at                     = NOW();
"""

SQL_PERFORMANCE = """
-- 2026-08-30 (kanban t_3ad38fa3): full refresh keyed on (ticker, listing_date).
-- 2026-09-02 (kanban t_e71cffde): return_day10_pct/return_day20_pct now landed
-- from silver return_10d/return_20d (10th/20th trading-day close vs offer);
-- the API's per-request day-20 lateral becomes a fallback only.
-- 2026-09-04 (kanban t_bcd1f540): exit leg of the post-listing drift rule
-- (enter +20td, hold 20td -> exit at the 40th trading day). return_day40_pct /
-- exit_day40_price / exit_day40_date landed from silver.unified_prices
-- (OFFSET 39, same convention as the API lateral, plus the recycled-ticker
-- next-listing guard); the API's per-request day-40 lateral becomes a fallback.
-- 2026-09-09 (kanban t_5b2c6fad): total_return_pct was return_3m*100 only, so
-- every IPO < ~3m old (silver return_3m not yet computable) got NULL — 0/43 in
-- the 3m window while current_price was fresh. Fallback: derive since-listing
-- return from the same current_price lateral: (current/offer - 1)*100.
-- Older rows keep the return_3m snapshot semantics (COALESCE first arm).
-- Populated horizons: first_day_return_pct, return_day10/20/30/40_pct,
-- total_return_pct (3m snapshot, else since-listing from current_price).
-- day3/5/60/90, high/low/drawdown, vs_ipo_index stay NULL (not in silver).
DELETE FROM gold.hk_ipo_performance;
INSERT INTO gold.hk_ipo_performance
  (ticker, listing_date, offer_price,
   first_day_open, first_day_close, first_day_volume, first_day_return_pct,
   return_day3_pct, return_day5_pct, return_day10_pct, return_day20_pct,
   return_day30_pct,
   return_day40_pct, exit_day40_price, exit_day40_date,
   current_price, total_return_pct,
   high_since_listing, low_since_listing, max_drawdown_pct,
   performance_tier, updated_at)
SELECT
  p.ticker,
  p.listing_date,
  p.offer_price,
  p.first_day_open,
  p.first_day_close,
  p.first_day_volume,
  p.return_1d * 100 AS first_day_return_pct,
  NULL AS return_day3_pct,
  NULL AS return_day5_pct,
  p.return_10d * 100 AS return_day10_pct,
  p.return_20d * 100 AS return_day20_pct,
  p.return_1m * 100 AS return_day30_pct,
  -- exit leg (40th trading day): NULL until 40 trading days have elapsed.
  CASE WHEN d40.close IS NOT NULL AND p.offer_price > 0
       THEN (d40.close / p.offer_price - 1) * 100
  END AS return_day40_pct,
  d40.close AS exit_day40_price,
  d40.dt AS exit_day40_date,
  cur.close AS current_price,
  COALESCE(
    p.return_3m * 100,
    CASE WHEN cur.close IS NOT NULL AND p.offer_price > 0
         THEN (cur.close / p.offer_price - 1) * 100
    END
  ) AS total_return_pct,
  NULL AS high_since_listing,
  NULL AS low_since_listing,
  NULL AS max_drawdown_pct,
  -- 2026-09-02 (kanban t_2f98c3be): tier audit. Tier is a 3-MONTH total-return
  -- bucket (NOT first-day). Bug: NULL return_3m (IPO < ~3m old or missing
  -- prices) fell into ELSE -> 'poor', mislabeling 164 recent rows (e.g.
  -- 2261.HK +64% day-1 stamped 'poor'). Now NULL until 3m return exists.
  CASE
    WHEN p.return_3m IS NULL THEN NULL
    WHEN p.return_3m > 0.5  THEN 'strong'
    WHEN p.return_3m > 0    THEN 'positive'
    WHEN p.return_3m > -0.2 THEN 'weak'
    ELSE 'poor'
  END AS performance_tier,
  NOW()
FROM silver.unified_ipo_performance p
LEFT JOIN LATERAL (
  SELECT MIN(c2.listing_date) AS next_ld
  FROM silver.unified_ipo_calendar c2
  WHERE c2.ticker = p.ticker AND c2.listing_date > p.listing_date
) nxt ON TRUE
LEFT JOIN LATERAL (
  SELECT u.close AS close
  FROM silver.unified_prices u
  WHERE u.ticker = p.ticker
    AND (nxt.next_ld IS NULL OR u.date < nxt.next_ld)
  ORDER BY u.date DESC LIMIT 1
) cur ON TRUE
LEFT JOIN LATERAL (
  SELECT u.close AS close, u.date AS dt
  FROM silver.unified_prices u
  WHERE u.ticker = p.ticker
    AND u.date >= p.listing_date
    AND (nxt.next_ld IS NULL OR u.date < nxt.next_ld)
  ORDER BY u.date OFFSET 39 LIMIT 1
) d40 ON TRUE
-- 2026-09-17 (kanban t_a6b7e5aa): one row per ticker. Every backend consumer
-- (backend/app/routes/hkex.py, 6 sites) joins performance on ticker ONLY, so
-- the 12 recycled tickers fanned out (e.g. 2076.HK/9868.HK twice in /ipos,
-- count 1928 vs 1926). gold.hk_ipo_calendar is keyed on ticker (frontend
-- convention: LATEST listing); performance now keeps only the event matching
-- that canonical listing_date. Earlier events stay available per-event in
-- silver.unified_ipo_performance (Pipeline B drift reads silver, not gold).
-- Enforced at DB level by hk_ipo_performance_ticker_uidx
-- (migrations/2026-09-17_hk_ipo_performance_ticker_unique.sql).
WHERE p.listing_date = (
  SELECT c.listing_date FROM gold.hk_ipo_calendar c WHERE c.ticker = p.ticker
)
ON CONFLICT (ticker, listing_date) DO UPDATE SET
  offer_price          = EXCLUDED.offer_price,
  first_day_open       = EXCLUDED.first_day_open,
  first_day_close      = EXCLUDED.first_day_close,
  first_day_volume     = EXCLUDED.first_day_volume,
  first_day_return_pct = EXCLUDED.first_day_return_pct,
  return_day10_pct = EXCLUDED.return_day10_pct,
  return_day20_pct = EXCLUDED.return_day20_pct,
  return_day30_pct     = EXCLUDED.return_day30_pct,
  return_day40_pct = EXCLUDED.return_day40_pct,
  exit_day40_price = EXCLUDED.exit_day40_price,
  exit_day40_date  = EXCLUDED.exit_day40_date,
  current_price    = EXCLUDED.current_price,
  total_return_pct = EXCLUDED.total_return_pct,
  performance_tier = EXCLUDED.performance_tier,
  updated_at       = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM silver.unified_ipo_calendar")
    count = cur.fetchone()[0]
    if count == 0:
        print("⚠️  silver.unified_ipo_calendar is empty, skipping gold IPO build")
        cur.close()
        conn.close()
        sys.exit(0)
    cur.execute(SQL_CALENDAR)
    print(f"✅ gold.hk_ipo_calendar updated: {cur.rowcount} rows upserted")
    cur.execute(SQL_DETAILS)
    print(f"✅ gold.hk_ipo_details updated: {cur.rowcount} rows upserted")
    cur.execute(SQL_PERFORMANCE)
    print(f"✅ gold.hk_ipo_performance updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
