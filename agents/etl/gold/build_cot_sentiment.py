#!/usr/bin/env python3
"""
Gold Transform: COT Sentiment (silver.cot_euro_fx_daily -> gold.cot_sentiment)
==============================================================================
Standalone extraction of gold_builder.build_cot_sentiment() so the COT chain
can be wired into pipeline_manifest.json on its own. gold_builder itself is a
flagged MIXED-boundary script (2026-06-13 note: "do not add to Pipeline A or B
without splitting") and remains outside the manifest — see
skills/devops/etl-cron-pipeline-diagnosis/references/gold-builder-orphaned-writer.md.

Sentiment conventions — PRESERVED per instrument exactly as materialized in
gold.cot_sentiment today (kanban t_cf9c5c8b diagnosis 2026-07-30):
  EURO FX   written historically by gold_builder:
              sentiment  = net_noncomm > 50000 -> 'bullish',
                           net_noncomm < -50000 -> 'bearish', else 'neutral'
              signal_flag = |cot_z| > 1.5
  GC/CL/ES  written by the 2026-06 cot_expansion one-off (contrarian):
              sentiment  = cot_z > 1.0 -> 'bearish' (crowded longs),
                           cot_z < -1.0 -> 'bullish' (crowded shorts), else 'neutral'
              signal_flag = sentiment != 'neutral'
Downstream consumers (cot_contrarian_extreme, cl/es promotion candidates,
gc_cot_contrarian_inverse) read cot_z / net_noncomm directly, not sentiment.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
INSERT INTO gold.cot_sentiment
    (instrument, date, report_date, noncomm_long, noncomm_short,
     net_noncomm, cot_z, sentiment, signal_flag, updated_at)
SELECT
    instrument, date, report_date, noncomm_long, noncomm_short, net_noncomm, cot_z,
    CASE
        WHEN instrument = 'EURO FX' THEN
            CASE
                WHEN net_noncomm IS NULL THEN NULL
                WHEN net_noncomm > 50000 THEN 'bullish'
                WHEN net_noncomm < -50000 THEN 'bearish'
                ELSE 'neutral'
            END
        ELSE
            CASE
                WHEN cot_z IS NULL THEN 'neutral'
                WHEN cot_z::numeric > 1.0 THEN 'bearish'
                WHEN cot_z::numeric < -1.0 THEN 'bullish'
                ELSE 'neutral'
            END
    END,
    CASE
        WHEN instrument = 'EURO FX' THEN
            CASE WHEN cot_z IS NOT NULL AND ABS(cot_z::numeric) > 1.5 THEN 1 ELSE 0 END
        ELSE
            CASE WHEN cot_z IS NOT NULL AND ABS(cot_z::numeric) > 1.0 THEN 1 ELSE 0 END
    END,
    NOW()
FROM silver.cot_euro_fx_daily
ON CONFLICT (instrument, date) DO UPDATE SET
    report_date  = EXCLUDED.report_date,
    noncomm_long  = EXCLUDED.noncomm_long,
    noncomm_short = EXCLUDED.noncomm_short,
    net_noncomm   = EXCLUDED.net_noncomm,
    cot_z         = EXCLUDED.cot_z,
    sentiment     = EXCLUDED.sentiment,
    signal_flag   = EXCLUDED.signal_flag,
    updated_at    = NOW();
"""


def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    n = cur.rowcount
    conn.commit()
    cur.execute("""
        SELECT instrument, max(report_date), max(date), count(*)
        FROM gold.cot_sentiment GROUP BY instrument ORDER BY instrument
    """)
    print(f"✅ gold.cot_sentiment — {n} rows upserted")
    for r in cur.fetchall():
        print(f"   {r[0]}: max_report={r[1]} max_date={r[2]} rows={r[3]}")
    conn.close()


if __name__ == '__main__':
    run()
