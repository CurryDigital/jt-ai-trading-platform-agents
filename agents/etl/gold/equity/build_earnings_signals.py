# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Equity: Earnings Signals
Reads from: silver.unified_earnings
Writes to:  gold.earnings_signals, gold.earnings_data, gold.sue_scores

Classifies earnings surprises and builds trade signal windows.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
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
  eps_surprise_pct    = EXCLUDED.eps_surprise_pct,
  surprise_category   = EXCLUDED.surprise_category,
  signal_window_start = EXCLUDED.signal_window_start,
  signal_window_end   = EXCLUDED.signal_window_end,
  created_at          = NOW();
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
  fiscal_quarter = EXCLUDED.fiscal_quarter,
  actual_eps     = EXCLUDED.actual_eps,
  estimate_eps   = EXCLUDED.estimate_eps,
  surprise_pct   = EXCLUDED.surprise_pct,
  collected_at   = NOW();
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
  fiscal_quarter = EXCLUDED.fiscal_quarter,
  actual_eps     = EXCLUDED.actual_eps,
  estimate_eps   = EXCLUDED.estimate_eps,
  surprise_pct   = EXCLUDED.surprise_pct,
  sue            = EXCLUDED.sue,
  sue_decile     = EXCLUDED.sue_decile,
  sue_category   = EXCLUDED.sue_category,
  calculated_at  = NOW()
-- 2026-10-17: only rewrite (and re-stamp calculated_at) when a value actually
-- changed. Previously every daily run re-stamped all 17.8k rows, destroying
-- compute vintage (the 2026-08-05 handoff audit hit this).
WHERE gold.sue_scores.sue            IS DISTINCT FROM EXCLUDED.sue
   OR gold.sue_scores.sue_decile     IS DISTINCT FROM EXCLUDED.sue_decile
   OR gold.sue_scores.sue_category   IS DISTINCT FROM EXCLUDED.sue_category
   OR gold.sue_scores.actual_eps     IS DISTINCT FROM EXCLUDED.actual_eps
   OR gold.sue_scores.estimate_eps   IS DISTINCT FROM EXCLUDED.estimate_eps
   OR gold.sue_scores.surprise_pct   IS DISTINCT FROM EXCLUDED.surprise_pct;
"""

def run():
    from snapshot_guard import require_snapshot_id, log_snapshot
    snapshot_id = require_snapshot_id(
        "gold.sue_scores / gold.earnings_signals / gold.earnings_data (full upsert)",
        "gold/equity/build_earnings_signals.py")
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM gold.sue_scores")
    pre_sue = cur.fetchone()[0]
    cur.execute(SQL_SIGNALS)
    print(f"✅ gold.earnings_signals: {cur.rowcount} rows upserted")
    cur.execute(SQL_DATA)
    print(f"✅ gold.earnings_data: {cur.rowcount} rows upserted")
    cur.execute(SQL_SUE)
    print(f"✅ gold.sue_scores: {cur.rowcount} rows upserted")
    cur.execute("SELECT count(*) FROM gold.sue_scores")
    post_sue = cur.fetchone()[0]
    log_snapshot(cur, snapshot_id,
                 "gold.sue_scores full upsert", "gold/equity/build_earnings_signals.py",
                 pre_sue, post_sue,
                 f"rowcounts this run in stdout; calculated_at only re-stamped on value change")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
