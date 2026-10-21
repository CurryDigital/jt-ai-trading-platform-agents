#!/usr/bin/env python3
"""
Consumption: refresh mark-to-market prices from gold.daily_ohlcv.

Why this exists:
  The 22:30 UTC US post-close top-up refreshes bronze/silver/gold after the
  US cash close, but the strategies-detail consumption tables are normally
  written only by the 09:15 UTC signal cycle. Without a marks-only refresh,
  US equity current_price values lag one session from Friday evening until
  Monday morning (seen 2026-08-21: HPE gold close 53.45, consumption 52.89).

Semantics (UPDATE-only, idempotent, no ledger/signal mutation):
  - consumption.portfolio_positions_current (PAPER_TRADING ACTIVE rows):
      current_price  = latest gold.daily_ohlcv close
      market_value   = quantity * current_price
      unrealized_pnl = quantity * (current_price - entry_price)
  - consumption.strategies_signals_current:
      current_price  = latest gold.daily_ohlcv close
      signal/signal_strength/confidence_score are NOT touched.

Runs after gold_builder in yf_us_postclose_topup.sh.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# consumption current_price columns are numeric(15,4)/(16,4) while
# gold.daily_ohlcv.close is numeric(18,8); compare/store at 4dp so the
# refresh is idempotent instead of rewriting every row on every run.
LATEST_CLOSE_CTE = """
WITH latest AS (
    SELECT DISTINCT ON (ticker) ticker, ROUND(close, 4) AS close, date
    FROM gold.daily_ohlcv
    WHERE close IS NOT NULL
    ORDER BY ticker, date DESC
)
"""

UPDATE_POSITIONS_SQL = LATEST_CLOSE_CTE + """
UPDATE consumption.portfolio_positions_current c
SET current_price  = b.close,
    market_value   = c.quantity * b.close,
    unrealized_pnl = c.quantity * (b.close - c.entry_price),
    updated_at     = NOW()
FROM latest b
WHERE c.ticker = b.ticker
  AND c.execution_mode = 'PAPER_TRADING'
  AND c.status = 'ACTIVE'
  AND c.current_price IS DISTINCT FROM b.close;
"""

UPDATE_SIGNALS_SQL = LATEST_CLOSE_CTE + """
UPDATE consumption.strategies_signals_current s
SET current_price = b.close,
    updated_at    = NOW()
FROM latest b
WHERE s.ticker = b.ticker
  AND s.current_price IS DISTINCT FROM b.close;
"""

VERIFY_MISMATCHES_SQL = LATEST_CLOSE_CTE + """
SELECT
  (SELECT COUNT(*)
   FROM consumption.portfolio_positions_current c
   JOIN latest b ON b.ticker = c.ticker
   WHERE c.execution_mode = 'PAPER_TRADING'
     AND c.status = 'ACTIVE'
     AND c.current_price IS DISTINCT FROM b.close) AS position_mismatches,
  (SELECT COUNT(*)
   FROM consumption.strategies_signals_current s
   JOIN latest b ON b.ticker = s.ticker
   WHERE s.current_price IS DISTINCT FROM b.close) AS signal_mismatches;
"""

VERIFY_HPE_SQL = """
SELECT 'portfolio_positions_current' AS table_name, strategy_id, ticker,
       current_price, market_value, unrealized_pnl, updated_at
FROM consumption.portfolio_positions_current
WHERE ticker = 'HPE'
UNION ALL
SELECT 'strategies_signals_current' AS table_name, strategy_id, ticker,
       current_price, NULL AS market_value, NULL AS unrealized_pnl, updated_at
FROM consumption.strategies_signals_current
WHERE ticker = 'HPE'
ORDER BY table_name, strategy_id;
"""


def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(UPDATE_POSITIONS_SQL)
    pos_updated = cur.rowcount
    print(f"✅ portfolio_positions_current marks refreshed: {pos_updated} row(s)")

    cur.execute(UPDATE_SIGNALS_SQL)
    sig_updated = cur.rowcount
    print(f"✅ strategies_signals_current marks refreshed: {sig_updated} row(s)")

    cur.execute(VERIFY_MISMATCHES_SQL)
    pos_mm, sig_mm = cur.fetchone()
    print(f"📊 post-refresh mismatches vs gold.daily_ohlcv: positions={pos_mm}, signals={sig_mm}")

    cur.execute(VERIFY_HPE_SQL)
    rows = cur.fetchall()
    for table_name, sid, ticker, price, mv, pnl, updated_at in rows:
        print(f"   HPE {table_name} {sid}: current_price={price} market_value={mv} unrealized_pnl={pnl} updated_at={updated_at}")

    conn.commit()
    conn.close()

    if pos_mm or sig_mm:
        print("⚠️ residual mismatches remain (tickers without a gold bar are expected to keep old marks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
