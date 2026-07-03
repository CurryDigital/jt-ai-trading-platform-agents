#!/usr/bin/env python3
"""
Gold Strategy: Strategy Scores & Backtest Results
Reads from: gold.kpis_metrics, gold.strategy_registry (universe_tickers),
            gold.strategy_signal_criteria
Writes to:  gold.strategy_ticker_scores, gold.strategy_registry

2026-07-03: assignments now unnest gold.strategy_registry.universe_tickers
instead of reading gold.strategy_universes. strategy_universes is a
separate, empty table nothing in this codebase ever writes to; the same
ticker-universe data already lives on strategy_registry (populated at
strategy-onboarding time), so this was silently starving the whole scoring
pipeline (0 assignments -> 0 scores -> 0 dashboard opportunities), not a
missing-data problem.

2026-07-03: criterion evaluation is now generic (criterion_name/operator
looked up dynamically against gold.kpis_metrics via to_jsonb(), both
numeric and boolean columns) instead of a hardcoded CASE covering exactly
4 column names. The hardcoded version silently scored every strategy 0
whose criteria didn't happen to be one of those 4 names/operators (e.g.
S9_MACD_Momentum_V2's real criteria are macd_histogram/prev_macd_histogram/
volume_ratio with >=, none of which matched) -- onboarding any new
strategy meant editing this file's SQL by hand. prev_macd_histogram (not
a real column) is resolved via a second-latest-row-per-ticker CTE.
"""
import sys, os, json
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# Columns criteria are allowed to reference beyond real gold.kpis_metrics
# columns -- computed here because they're not stored (e.g. "yesterday's"
# value of a column). Maps synthetic name -> the real column it shadows.
SYNTHETIC_PREV_COLUMNS = {
    "prev_macd_histogram": "macd_histogram",
}

SQL_SCORES = """
INSERT INTO gold.strategy_ticker_scores
  (strategy_id, ticker, score, signal_action, entry_score, exit_score,
   criteria_met, position_status, deployed_at, updated_at)

WITH criteria AS (
  SELECT
    sc.strategy_id,
    sc.signal_type,
    sc.criterion_name,
    sc.operator,
    sc.threshold,
    sc.logic_mode
  FROM gold.strategy_signal_criteria sc
  WHERE sc.signal_type = 'buy'
),
assignments AS (
  SELECT strategy_id, UNNEST(universe_tickers) AS ticker
  FROM gold.strategy_registry
  WHERE retired_at IS NULL
),
latest_kpis AS (
  SELECT DISTINCT ON (ticker) *
  FROM gold.kpis_metrics
  ORDER BY ticker, date DESC
),
prev_kpis AS (
  SELECT DISTINCT ON (k.ticker) k.ticker, k.macd_histogram AS prev_macd_histogram
  FROM gold.kpis_metrics k
  JOIN latest_kpis lk ON lk.ticker = k.ticker AND k.date < lk.date
  ORDER BY k.ticker, k.date DESC
),
kpis_row AS (
  SELECT lk.*, pk.prev_macd_histogram
  FROM latest_kpis lk
  LEFT JOIN prev_kpis pk USING (ticker)
),
criteria_eval AS (
  SELECT
    a.strategy_id,
    a.ticker,
    c.logic_mode,
    CASE
      WHEN (to_jsonb(k.*) ->> c.criterion_name) IN ('true', 'false') THEN
        CASE c.operator
          WHEN '!=' THEN (to_jsonb(k.*) ->> c.criterion_name)::boolean IS DISTINCT FROM (c.threshold <> 0)
          ELSE            (to_jsonb(k.*) ->> c.criterion_name)::boolean =              (c.threshold <> 0)
        END
      ELSE
        CASE c.operator
          WHEN '>'  THEN (to_jsonb(k.*) ->> c.criterion_name)::numeric >  c.threshold
          WHEN '<'  THEN (to_jsonb(k.*) ->> c.criterion_name)::numeric <  c.threshold
          WHEN '>=' THEN (to_jsonb(k.*) ->> c.criterion_name)::numeric >= c.threshold
          WHEN '<=' THEN (to_jsonb(k.*) ->> c.criterion_name)::numeric <= c.threshold
          WHEN '='  THEN (to_jsonb(k.*) ->> c.criterion_name)::numeric =  c.threshold
          WHEN '!=' THEN (to_jsonb(k.*) ->> c.criterion_name)::numeric != c.threshold
        END
    END AS criterion_met
  FROM assignments a
  JOIN kpis_row k USING (ticker)
  JOIN criteria c USING (strategy_id)
),
signal_eval AS (
  SELECT
    strategy_id,
    ticker,
    ROUND(100.0 * COUNT(*) FILTER (WHERE criterion_met) / NULLIF(COUNT(*), 0), 2) AS score,
    CASE MAX(logic_mode)
      WHEN 'all' THEN BOOL_AND(COALESCE(criterion_met, FALSE))
      ELSE            BOOL_OR(COALESCE(criterion_met, FALSE))
    END AS has_entry_signal
  FROM criteria_eval
  GROUP BY strategy_id, ticker
)
SELECT
  strategy_id,
  ticker,
  COALESCE(score, 0),
  CASE WHEN has_entry_signal THEN 'BUY' ELSE 'HOLD' END,
  COALESCE(score, 0),
  0.0,
  '{}'::jsonb,
  'NONE',
  NOW(),
  NOW()
FROM signal_eval

ON CONFLICT (strategy_id, ticker) DO UPDATE SET
  score          = EXCLUDED.score,
  signal_action  = EXCLUDED.signal_action,
  entry_score    = EXCLUDED.entry_score,
  exit_score     = EXCLUDED.exit_score,
  updated_at     = NOW();
"""

SQL_UNKNOWN_CRITERIA = """
SELECT DISTINCT sc.criterion_name
FROM gold.strategy_signal_criteria sc
WHERE sc.criterion_name NOT IN (
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'gold' AND table_name = 'kpis_metrics'
)
AND sc.criterion_name NOT IN %(synthetic)s;
"""

# NOT FIXED — flagged, not guessed: gold.strategy_backtests.strategy_id is
# smallint (the agents/signals/ registry.json numeric id space, 1-20),
# while gold.strategy_registry.strategy_id is varchar (semantic ids like
# "btc_funding_mean_rev_short"). ::varchar cast never bridges these two id
# spaces, so this UPDATE matches 0 rows against real data today. Needs an
# operator decision on which id space gold.strategy_backtests should key
# on before this can be fixed — not something to guess-map silently.
SQL_REGISTRY_SYNC = """
UPDATE gold.strategy_registry sr
SET
  win_rate_oos  = b.win_rate,
  sharpe_oos    = b.sharpe,
  max_drawdown_oos = ABS(b.max_dd),
  updated_at    = NOW()
FROM (
  SELECT DISTINCT ON (strategy_id)
    strategy_id,
    win_rate,
    sharpe,
    max_dd
  FROM gold.strategy_backtests
  ORDER BY strategy_id, run_date DESC
) b
WHERE sr.strategy_id = b.strategy_id::varchar;
"""

def run():
    conn = get_connection()
    cur = conn.cursor()

    # Check if required tables have data
    cur.execute("SELECT COUNT(*) FROM gold.strategy_signal_criteria")
    if cur.fetchone()[0] == 0:
        print("⚠️  gold.strategy_signal_criteria empty — skipping strategy scores")
        conn.close()
        return

    # Loud, not silent: a criterion_name that isn't a real kpis_metrics
    # column (typo, renamed column, etc.) would otherwise just never match
    # anything and quietly drag that strategy's score toward 0.
    cur.execute(SQL_UNKNOWN_CRITERIA, {"synthetic": tuple(SYNTHETIC_PREV_COLUMNS)})
    unknown = [r[0] for r in cur.fetchall()]
    if unknown:
        print(f"⚠️  criterion_name(s) not found on gold.kpis_metrics (will never match): {unknown}")

    cur.execute(SQL_SCORES)
    print(f"✅ gold.strategy_ticker_scores updated: {cur.rowcount} rows upserted")

    cur.execute(SQL_REGISTRY_SYNC)
    print(f"✅ gold.strategy_registry synced: {cur.rowcount} rows updated")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
