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
INSERT INTO gold.hk_ipo_calendar
  (ticker, stock_name, listing_date, offer_price, currency,
   market_cap_hkd, market_cap_usd, sector, sub_sector,
   sponsor, underwriters, shares_offered, greenshoe_shares,
   board, is_active, updated_at)
SELECT
  ticker, stock_name, listing_date, offer_price, currency,
  market_cap_hkd, market_cap_usd, sector, sub_sector,
  sponsor, underwriters, shares_offered, greenshoe_shares,
  'MAIN' AS board, TRUE AS is_active, NOW()
FROM silver.unified_ipo_calendar
ON CONFLICT (ticker) DO UPDATE SET
  listing_date    = EXCLUDED.listing_date,
  market_cap_hkd  = EXCLUDED.market_cap_hkd,
  is_active       = EXCLUDED.is_active,
  updated_at      = NOW();
"""

SQL_DETAILS = """
INSERT INTO gold.hk_ipo_details
  (ticker, oversubscription_retail, oversubscription_institutional,
   oversubscription_total, cornerstone_total_pct, cornerstone_investors,
   lockup_period_days, greenshoe_pct, listing_date, updated_at)
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
  NOW()
FROM silver.unified_ipo_calendar c
ON CONFLICT (ticker) DO UPDATE SET
  oversubscription_retail        = EXCLUDED.oversubscription_retail,
  oversubscription_institutional = EXCLUDED.oversubscription_institutional,
  updated_at                     = NOW();
"""

SQL_PERFORMANCE = """
INSERT INTO gold.hk_ipo_performance
  (ticker, listing_date, offer_price,
   first_day_open, first_day_close, first_day_volume, first_day_return_pct,
   return_day3_pct, return_day5_pct, return_day10_pct, return_day30_pct,
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
  p.return_day1 AS first_day_return_pct,
  p.return_day3  AS return_day3_pct,
  p.return_day5  AS return_day5_pct,
  p.return_day10 AS return_day10_pct,
  p.return_day30 AS return_day30_pct,
  -- current price = close from latest price data
  (SELECT close FROM silver.unified_prices
   WHERE ticker = p.ticker ORDER BY date DESC LIMIT 1) AS current_price,
  p.return_current AS total_return_pct,
  p.high_since_listing,
  p.low_since_listing,
  (p.low_since_listing / NULLIF(p.high_since_listing, 0) - 1) * 100 AS max_drawdown_pct,
  CASE
    WHEN p.return_current > 0.5  THEN 'strong'
    WHEN p.return_current > 0    THEN 'positive'
    WHEN p.return_current > -0.2 THEN 'weak'
    ELSE 'poor'
  END AS performance_tier,
  NOW()
FROM silver.unified_ipo_performance p
ON CONFLICT (ticker) DO UPDATE SET
  current_price    = EXCLUDED.current_price,
  total_return_pct = EXCLUDED.total_return_pct,
  performance_tier = EXCLUDED.performance_tier,
  updated_at       = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
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
