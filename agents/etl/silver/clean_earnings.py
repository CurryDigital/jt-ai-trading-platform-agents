#!/usr/bin/env python3
"""
Silver: Unified Earnings
Reads from: bronze.earnings_calendar, bronze.fmp_earnings,
            bronze.fmp_earnings_surprises, bronze.manual_earnings
Writes to:  silver.unified_earnings

Rules:
  - Deduplicate by (ticker, report_date), prefer manual > fmp > yf
  - Compute eps_surprise_pct, sue_score, sue_decile
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

# Load Hermes env file
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'))

from db import get_connection

SQL_MERGE = """
INSERT INTO silver.unified_earnings
  (ticker, report_date, fiscal_quarter, eps_estimate, eps_actual,
   eps_surprise_pct, eps_surprise_dollar, revenue_estimate, revenue_actual,
   revenue_surprise_pct, primary_source, updated_at)

WITH ranked AS (
  -- YF earnings calendar (priority 1)
  SELECT
    e.ticker, e.earnings_date AS report_date, e.fiscal_quarter,
    e.eps_estimate, e.eps_actual, e.eps_surprise_pct, NULL::numeric AS eps_surprise_dollar,
    e.revenue_estimate, e.revenue_actual, NULL::numeric AS revenue_surprise_pct,
    'yfinance' AS source, 1 AS priority
  FROM bronze.earnings_calendar e

  UNION ALL

  -- Manual earnings (priority 0 — overrides everything)
  SELECT
    m.ticker, m.report_date, m.fiscal_quarter,
    m.eps_estimate, m.eps_actual,
    CASE WHEN m.eps_estimate <> 0
         THEN (m.eps_actual - m.eps_estimate) / ABS(m.eps_estimate) * 100
    END,
    m.eps_actual - m.eps_estimate,
    m.revenue_estimate, m.revenue_actual, NULL::numeric,
    'manual' AS source, 0 AS priority
  FROM bronze.manual_earnings m
),
best AS (
  SELECT DISTINCT ON (ticker, report_date) *
  FROM ranked
  ORDER BY ticker, report_date, priority ASC
)
SELECT
  ticker, report_date, fiscal_quarter, eps_estimate, eps_actual,
  eps_surprise_pct, eps_actual - eps_estimate AS eps_surprise_dollar, revenue_estimate, revenue_actual,
  revenue_surprise_pct, source, NOW()
FROM best

ON CONFLICT (ticker, report_date) DO UPDATE SET
  eps_actual         = EXCLUDED.eps_actual,
  eps_surprise_pct   = EXCLUDED.eps_surprise_pct,
  primary_source     = EXCLUDED.primary_source,
  updated_at         = NOW();
"""

SQL_SUE = """
UPDATE silver.unified_earnings e
SET
  sue_score   = (e.eps_actual - e.eps_estimate)
                  / NULLIF(STDDEV(e.eps_actual - e.eps_estimate) OVER
                      (PARTITION BY e.ticker ORDER BY e.report_date
                       ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING), 0),
  sue_decile  = NTILE(10) OVER (PARTITION BY DATE_TRUNC('quarter', e.report_date)
                                ORDER BY e.eps_surprise_pct NULLS LAST),
  sue_category = CASE
    WHEN e.eps_surprise_pct > 10  THEN 'strong_beat'
    WHEN e.eps_surprise_pct > 2   THEN 'beat'
    WHEN e.eps_surprise_pct >= -2 THEN 'inline'
    WHEN e.eps_surprise_pct >= -10 THEN 'miss'
    ELSE 'strong_miss'
  END;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SQL_MERGE)
    print(f"✅ silver.unified_earnings merged: {cur.rowcount} rows upserted")

    # SUE scores need a writeable CTE — run as separate statement
    cur.execute("""
        WITH sue AS (
          SELECT
            id,
            (eps_actual - eps_estimate)
              / NULLIF(STDDEV(eps_actual - eps_estimate) OVER
                  (PARTITION BY ticker ORDER BY report_date
                   ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING), 0) AS sue_score,
            CASE
              WHEN eps_surprise_pct > 10  THEN 'strong_beat'
              WHEN eps_surprise_pct > 2   THEN 'beat'
              WHEN eps_surprise_pct >= -2 THEN 'inline'
              WHEN eps_surprise_pct >= -10 THEN 'miss'
              ELSE 'strong_miss'
            END AS sue_category
          FROM silver.unified_earnings
        )
        UPDATE silver.unified_earnings e
        SET sue_score    = s.sue_score,
            sue_category = s.sue_category
        FROM sue s WHERE e.id = s.id;
    """)
    print(f"✅ silver.unified_earnings sue_score updated: {cur.rowcount} rows")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
