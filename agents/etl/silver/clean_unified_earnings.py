#!/usr/bin/env python3
"""
Silver Transform: Unified Earnings
Merges bronze.fmp_earnings + bronze.manual_earnings + bronze.earnings_calendar
→ silver.unified_earnings (with SUE score calculation)
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

UPSERT_SQL = """
INSERT INTO silver.unified_earnings
    (ticker, report_date, fiscal_quarter, eps_estimate, eps_actual,
     eps_surprise_pct, eps_surprise_dollar, revenue_estimate, revenue_actual,
     revenue_surprise_pct, time_of_day, sue_score, sue_decile, sue_category,
     primary_source, all_sources, updated_at)
WITH ranked AS (
    SELECT ticker, report_date, fiscal_quarter,
        eps_estimate, eps_actual, NULL::numeric AS revenue_estimate,
        NULL::numeric AS revenue_actual, NULL AS time_of_day,
        'fmp' AS src, 1 AS priority
    FROM bronze.fmp_earnings

    UNION ALL

    SELECT ticker, report_date, fiscal_quarter,
        eps_estimate, eps_actual,
        revenue_estimate::numeric, revenue_actual::numeric,
        NULL AS time_of_day,
        'manual', 2
    FROM bronze.manual_earnings

    UNION ALL

    SELECT ticker, earnings_date AS report_date, fiscal_quarter,
        eps_estimate, eps_actual,
        revenue_estimate::numeric, revenue_actual::numeric,
        NULL AS time_of_day,
        'yfinance', 3
    FROM bronze.earnings_calendar
),
best AS (
    SELECT DISTINCT ON (ticker, report_date) *
    FROM ranked
    ORDER BY ticker, report_date, priority
),
with_sue AS (
    SELECT *,
        -- EPS surprise %
        ROUND(
            (eps_actual - eps_estimate) / NULLIF(ABS(eps_estimate), 0) * 100,
            4
        ) AS eps_surprise_pct,
        (eps_actual - eps_estimate) AS eps_surprise_dollar,
        -- Revenue surprise %
        ROUND(
            (revenue_actual - revenue_estimate) / NULLIF(ABS(revenue_estimate), 0) * 100,
            4
        ) AS revenue_surprise_pct,
        -- Simplified SUE score = eps_surprise / rolling std (approximated)
        ROUND(
            (eps_actual - eps_estimate) / NULLIF(
                STDDEV(eps_actual - eps_estimate) OVER (
                    PARTITION BY ticker ORDER BY report_date
                    ROWS BETWEEN 7 PRECEDING AND 1 PRECEDING
                ), 0
            ), 8
        ) AS sue_score
    FROM best
)
SELECT
    ticker, report_date, fiscal_quarter,
    eps_estimate, eps_actual,
    eps_surprise_pct, eps_surprise_dollar,
    revenue_estimate, revenue_actual,
    revenue_surprise_pct, time_of_day,
    sue_score,
    NTILE(10) OVER (ORDER BY sue_score NULLS LAST) AS sue_decile,
    CASE
        WHEN sue_score > 2  THEN 'STRONG_BEAT'
        WHEN sue_score > 0  THEN 'BEAT'
        WHEN sue_score > -2 THEN 'MISS'
        ELSE 'STRONG_MISS'
    END AS sue_category,
    src AS primary_source,
    jsonb_build_array(src) AS all_sources,
    NOW() AS updated_at
FROM with_sue
ON CONFLICT (ticker, report_date) DO UPDATE SET
    eps_estimate       = EXCLUDED.eps_estimate,
    eps_actual         = EXCLUDED.eps_actual,
    eps_surprise_pct   = EXCLUDED.eps_surprise_pct,
    sue_score          = EXCLUDED.sue_score,
    sue_decile         = EXCLUDED.sue_decile,
    sue_category       = EXCLUDED.sue_category,
    updated_at         = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(UPSERT_SQL)
        print(f"✅ silver.unified_earnings — {cur.rowcount} rows upserted")
        conn.commit()
    except Exception as e:
        print(f"⚠️  FMP earnings skipped: {e}")
        conn.rollback()
    conn.close()

if __name__ == "__main__":
    run()
