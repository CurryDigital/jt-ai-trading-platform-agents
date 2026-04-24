#!/usr/bin/env python3
"""
Gold Equity: Earnings Signals
Reads from: silver.unified_earnings
Writes to:  gold.earnings_signals, gold.earnings_data, gold.sue_scores

Classifies earnings surprises and builds trade signal windows.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_SIGNALS = """
INSERT INTO gold.earnings_signals
  (symbol, earnings_date, eps_surprise_pct, surprise_category,
   signal_window_start, signal_window_end, created_at)
SELECT
  ticker AS symbol,
  report_date AS earnings_date,
  eps_surprise_pct,
  CASE
    WHEN eps_surprise_pct >  10 THEN 'beat'
    WHEN eps_surprise_pct >= 0  THEN 'inline'
    ELSE 'miss'
  END AS surprise_category,
  report_date - INTERVAL '1 day'  AS signal_window_start,
  report_date + INTERVAL '5 days' AS signal_window_end,
  NOW()
FROM silver.unified_earnings
WHERE eps_surprise_pct IS NOT NULL
ON CONFLICT (symbol, earnings_date) DO UPDATE SET
  eps_surprise_pct  = EXCLUDED.eps_surprise_pct,
  surprise_category = EXCLUDED.surprise_category;
"""

SQL_DATA = """
INSERT INTO gold.earnings_data
  (ticker, report_date, fiscal_quarter, actual_eps, estimate_eps, surprise_pct, collected_at)
SELECT
  ticker, report_date, fiscal_quarter,
  eps_actual, eps_estimate, eps_surprise_pct,
  NOW()
FROM silver.unified_earnings
ON CONFLICT (ticker, report_date) DO UPDATE SET
  actual_eps   = EXCLUDED.actual_eps,
  surprise_pct = EXCLUDED.surprise_pct;
"""

SQL_SUE = """
INSERT INTO gold.sue_scores
  (ticker, report_date, fiscal_quarter, actual_eps, estimate_eps,
   surprise_pct, sue, sue_decile, sue_category, calculated_at)
SELECT
  ticker, report_date, fiscal_quarter,
  eps_actual, eps_estimate, eps_surprise_pct,
  sue_score, sue_decile, sue_category,
  NOW()
FROM silver.unified_earnings
WHERE sue_score IS NOT NULL
ON CONFLICT (ticker, report_date) DO UPDATE SET
  sue         = EXCLUDED.sue,
  sue_decile  = EXCLUDED.sue_decile,
  sue_category = EXCLUDED.sue_category;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL_SIGNALS)
    print(f"✅ gold.earnings_signals: {cur.rowcount} rows upserted")
    cur.execute(SQL_DATA)
    print(f"✅ gold.earnings_data: {cur.rowcount} rows upserted")
    cur.execute(SQL_SUE)
    print(f"✅ gold.sue_scores: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
