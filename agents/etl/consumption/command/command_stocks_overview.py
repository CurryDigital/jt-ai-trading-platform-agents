#!/usr/bin/env python3
"""
Consumption: Command Tab — Stocks Overview & Top Opportunities
Reads from: gold.kpis_metrics, gold.asset_registry, gold.strategy_ticker_scores,
            gold.strategy_registry (opportunities ranking + live-strategy count —
            sharpe_oos, name, status)
Writes to:  consumption.markets_stocks_overview,
            consumption.dashboard_opportunities_top,
            consumption.dashboard_summary_cards

2026-07-01: no longer reads gold.strategy_definitions at all — its status
vocabulary (approved/rejected/retired/backtesting) is an approval-workflow
state, not an execution state, so it couldn't correctly answer either
"expected_return_pct" (no sharpe_ratio column) or "is this strategy live"
(no 'live' value in its domain). gold.strategy_registry answers both.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL_STOCKS = """
INSERT INTO consumption.markets_stocks_overview
  (ticker, name, sector, industry, market,
   price, change_pct, change_value, volume, avg_volume, volume_ratio,
   trend, rsi_14,
   distance_to_52w_high_pct, distance_to_52w_low_pct,
   strategy_signals, top_strategy_score,
   signal, signal_strength, asset_class, updated_at)

WITH latest_kpis AS (
  SELECT DISTINCT ON (ticker) *
  FROM gold.kpis_metrics
  ORDER BY ticker, date DESC
),
strategy_agg AS (
  SELECT
    ticker,
    MAX(score) AS top_score,
    JSONB_OBJECT_AGG(strategy_id, score) AS signals
  FROM gold.strategy_ticker_scores
  GROUP BY ticker
)
SELECT
  k.ticker,
  ar.name,
  ar.sector,
  NULL AS industry,
  ar.market,
  k.close AS price,
  k.change_1d AS change_pct,
  k.close * k.change_1d / 100 AS change_value,
  k.volume,
  k.vol_sma_20 AS avg_volume,
  k.vol_ratio AS volume_ratio,
  CASE
    WHEN k.cond_above_sma50  THEN 'up'
    WHEN k.cond_below_sma50  THEN 'down'
    ELSE 'sideways'
  END AS trend,
  k.rsi_14,
  -- Distance to 52w high/low from kpis (not stored directly, approximate)
  NULL AS distance_to_52w_high_pct,
  NULL AS distance_to_52w_low_pct,
  COALESCE(sa.signals, '{}'::jsonb) AS strategy_signals,
  COALESCE(sa.top_score, 0) AS top_strategy_score,
  CASE
    WHEN k.s001_high_vol_pullback OR k.s002_oversold_bounce OR k.s007_3day_monday OR k.s012_tech_momentum
    THEN 'BUY'
    ELSE 'HOLD'
  END AS signal,
  COALESCE(sa.top_score / 100, 0) AS signal_strength,
  ar.asset_class,
  NOW()
FROM latest_kpis k
JOIN gold.asset_registry ar ON ar.ticker = k.ticker
LEFT JOIN strategy_agg sa ON sa.ticker = k.ticker

ON CONFLICT (ticker) DO UPDATE SET
  price            = EXCLUDED.price,
  change_pct       = EXCLUDED.change_pct,
  rsi_14           = EXCLUDED.rsi_14,
  strategy_signals = EXCLUDED.strategy_signals,
  top_strategy_score = EXCLUDED.top_strategy_score,
  signal           = EXCLUDED.signal,
  updated_at       = NOW();
"""

# 2026-07-01: was joining gold.strategy_definitions, which has NO
# sharpe_ratio column at all, and no `name` column either (it's
# `strategy_name` there) — both would UndefinedColumn. Verified against
# db_setup/DDL_full_schema.sql: gold.strategy_registry has strategy_id,
# name, AND sharpe_oos (the strategy's real out-of-sample performance —
# the semantically correct source for "expected_return_pct", not a
# per-ticker technical-indicator table that happens to also have a column
# called sharpe_ratio for something unrelated).
SQL_OPPORTUNITIES = """
DELETE FROM consumption.dashboard_opportunities_top;

INSERT INTO consumption.dashboard_opportunities_top
  (rank, ticker, name, asset_class, signal_type, direction, confidence,
   expected_return_pct, entry_price, stop_loss, take_profit, rationale, updated_at)
SELECT
  ROW_NUMBER() OVER (ORDER BY sts.score DESC) AS rank,
  sts.ticker,
  ar.name,
  ar.asset_class,
  sr.strategy_id AS signal_type,
  'LONG' AS direction,
  sts.score / 100 AS confidence,
  sr.sharpe_oos AS expected_return_pct,
  k.close AS entry_price,
  k.close * 0.97 AS stop_loss,
  k.close * 1.05 AS take_profit,
  sr.name AS rationale,
  NOW()
FROM gold.strategy_ticker_scores sts
JOIN gold.strategy_registry sr USING (strategy_id)
JOIN gold.asset_registry ar ON ar.ticker = sts.ticker
JOIN (
  SELECT DISTINCT ON (ticker) ticker, close
  FROM gold.kpis_metrics ORDER BY ticker, date DESC
) k ON k.ticker = sts.ticker
WHERE sts.score > 60
ORDER BY sts.score DESC
LIMIT 10;
"""

# 2026-07-01: 'strategies_live' was filtering gold.strategy_definitions
# WHERE status = 'ACTIVE'. Verified live data: that table's real status
# values are {approved, rejected, retired, backtesting} (all lowercase,
# none 'active'/'ACTIVE') — an APPROVAL-WORKFLOW vocabulary, not an
# execution-state one, so it can never represent "live" no matter what
# case is used. gold.strategy_registry.status is the right column: it
# has an actual CHECK constraint enumerating {'paper','live','paused',
# 'retired'} — 'live' is a first-class, enforced value there.
SQL_SUMMARY = """
INSERT INTO consumption.dashboard_summary_cards
  (card_key, card_title, value_display, value_numeric, change_pct, trend, last_updated)
VALUES
  ('active_signals', 'Active Signals',
   (SELECT COUNT(*)::text FROM gold.strategy_ticker_scores WHERE signal_action = 'BUY'),
   (SELECT COUNT(*) FROM gold.strategy_ticker_scores WHERE signal_action = 'BUY'),
   NULL, 'up', NOW()),
  ('strategies_live', 'Live Strategies',
   (SELECT COUNT(*)::text FROM gold.strategy_registry WHERE status = 'live'),
   (SELECT COUNT(*) FROM gold.strategy_registry WHERE status = 'live'),
   NULL, 'up', NOW())
ON CONFLICT (card_key) DO UPDATE SET
  value_display = EXCLUDED.value_display,
  value_numeric = EXCLUDED.value_numeric,
  last_updated  = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(SQL_STOCKS)
    print(f"✅ consumption.markets_stocks_overview: {cur.rowcount} rows upserted")

    # 2026-07-01: SQL_OPPORTUNITIES was defined above but never executed —
    # consumption.dashboard_opportunities_top has been permanently empty.
    # Reuses the same DISTINCT ON (ticker, date DESC) pattern already proven
    # safe/indexed in latest_kpis (idx_kpis_ticker_date_desc), bounded to
    # LIMIT 10, so this shouldn't meaningfully add to this script's runtime.
    #
    # Guard moved here (was previously wrapping the WHOLE function, checking
    # gold.strategy_definitions — a table SQL_STOCKS and SQL_SUMMARY don't
    # even reference, so a missing/empty strategy_definitions used to skip
    # everything unnecessarily). Now gates only the one query that actually
    # needs its dependency, and checks the table it now really joins:
    # gold.strategy_registry.
    cur.execute("SELECT to_regclass('gold.strategy_registry')")
    if cur.fetchone()[0] is None:
        print("⚠️ gold.strategy_registry does not exist — skipping dashboard_opportunities_top")
    else:
        cur.execute("SELECT COUNT(*) FROM gold.strategy_registry")
        if cur.fetchone()[0] == 0:
            print("⚠️ gold.strategy_registry empty — skipping dashboard_opportunities_top")
        else:
            cur.execute(SQL_OPPORTUNITIES)
            print(f"✅ consumption.dashboard_opportunities_top: {cur.rowcount} rows inserted")

    cur.execute(SQL_SUMMARY)
    print(f"✅ consumption.dashboard_summary_cards: {cur.rowcount} rows upserted")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
