#!/usr/bin/env python3
"""
Consumption: sync paper-strategy positions into portfolio_positions_current
from the canonical paper ledger gold.paper_trades_synthetic.

Reads from: gold.paper_trades_synthetic (status='open', evidence_class='forward_paper')
Writes to:  consumption.portfolio_positions_current (execution_mode='PAPER_TRADING')

Why this exists (t_749e13f0):
  /api/strategies/{id}/capital-pool reads
      SUM(capital), COUNT(*) FROM consumption.portfolio_positions_current
      WHERE strategy_id=:sid AND status='ACTIVE'
  but nothing refreshed paper rows from the paper ledger, so every paper
  strategy reported Used=$0 / Positions=0, and the only paper rows present
  were stale deploy-placeholder rows (capital=25000, trades_count=0) written
  by the backend deploy endpoints.

Semantics:
  - One ACTIVE row per open (strategy_id, ticker) in the ledger.
  - capital        = n_shares * entry_price (actual used capital)
  - quantity       = n_shares
  - current_price  = latest gold.daily_ohlcv close (t_646c098a mark-to-market;
                     falls back to entry_price when the ticker has no bar)
  - market_value   = n_shares * current_price
  - unrealized_pnl = n_shares * (current_price - entry_price)
  - trades_count   = number of ledger rows for (strategy_id, ticker), all statuses
  - source         = 'algo' (CHECK constraint allows algo/manual/ibkr only)
  - execution_mode = 'PAPER_TRADING'
  - Reconcile: paper rows whose (strategy_id, ticker) is no longer open in the
    ledger are DELETED (clears stale deploy placeholders like SPY/XLE).

Runs in the signal cycle AFTER gold/strategy/rebuild_paper_positions.py.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# Delete paper rows that no longer correspond to an open ledger position,
# or whose strategy is not actively paper-monitored (t_f51d67fe: the synthetic
# ledger is a shadow ledger for ALL approved pipeline strategies; only
# is_active=true strategies are genuinely paper trading, so surfacing shadow
# positions as ACTIVE PAPER_TRADING contradicted the registry state).
# Only touches execution_mode='PAPER_TRADING' rows — live IBKR/manual rows
# are owned by portfolio_positions_risk.py / build_manual_positions.py.
DELETE_STALE_SQL = """
DELETE FROM consumption.portfolio_positions_current c
WHERE c.execution_mode = 'PAPER_TRADING'
  AND (
      NOT EXISTS (
          SELECT 1 FROM gold.paper_trades_synthetic p
          WHERE p.status = 'open'
            AND p.evidence_class = 'forward_paper'
            AND p.strategy_id = c.strategy_id
            AND p.ticker = c.ticker
      )
      OR NOT EXISTS (
          SELECT 1 FROM gold.strategy_paper_monitoring pm
          WHERE pm.strategy_id = c.strategy_id
            AND pm.is_active = true
      )
  );
"""

UPSERT_SQL = """
INSERT INTO consumption.portfolio_positions_current
    (strategy_id, ticker, side, entry_date, entry_price, current_price,
     quantity, market_value, weight_pct, unrealized_pnl, realized_pnl,
     status, updated_at, source, capital, trades_count,
     execution_mode, created_at)
SELECT
    p.strategy_id,
    p.ticker,
    'LONG'                                   AS side,
    p.entry_date,
    p.entry_price,
    -- t_646c098a: mark to market with the latest gold.daily_ohlcv close
    -- (IBKR bars stale since 2026-07-03); fall back to entry_price when the
    -- ticker has no bar so rows never go NULL.
    COALESCE(b.close, p.entry_price)         AS current_price,
    p.n_shares                               AS quantity,
    p.n_shares * COALESCE(b.close, p.entry_price) AS market_value,
    NULL                                     AS weight_pct,
    p.n_shares * (COALESCE(b.close, p.entry_price) - p.entry_price)
                                             AS unrealized_pnl,
    0                                        AS realized_pnl,
    'ACTIVE'                                 AS status,
    NOW()                                    AS updated_at,
    'algo'                                   AS source,
    p.n_shares * p.entry_price               AS capital,
    tc.trades_count,
    'PAPER_TRADING'                          AS execution_mode,
    p.created_at
FROM gold.paper_trades_synthetic p
JOIN (
    SELECT strategy_id, ticker, COUNT(*) AS trades_count
    FROM gold.paper_trades_synthetic
    WHERE evidence_class = 'forward_paper'
    GROUP BY strategy_id, ticker
) tc ON tc.strategy_id = p.strategy_id AND tc.ticker = p.ticker
LEFT JOIN (
    SELECT DISTINCT ON (ticker) ticker, close, date
    FROM gold.daily_ohlcv
    WHERE close IS NOT NULL
    ORDER BY ticker, date DESC
) b ON b.ticker = p.ticker
WHERE p.status = 'open'
  AND p.evidence_class = 'forward_paper'
  -- t_f51d67fe: only actively paper-monitored strategies are genuinely paper
  -- trading; the synthetic ledger also holds shadow rows for other approved
  -- strategies which must not surface as ACTIVE PAPER_TRADING positions.
  AND EXISTS (
      SELECT 1 FROM gold.strategy_paper_monitoring pm
      WHERE pm.strategy_id = p.strategy_id
        AND pm.is_active = true
  )
ON CONFLICT (strategy_id, ticker) DO UPDATE SET
    side           = EXCLUDED.side,
    entry_date     = EXCLUDED.entry_date,
    entry_price    = EXCLUDED.entry_price,
    current_price  = EXCLUDED.current_price,
    quantity       = EXCLUDED.quantity,
    market_value   = EXCLUDED.market_value,
    unrealized_pnl = EXCLUDED.unrealized_pnl,
    realized_pnl   = EXCLUDED.realized_pnl,
    status         = EXCLUDED.status,
    source         = EXCLUDED.source,
    capital        = EXCLUDED.capital,
    trades_count   = EXCLUDED.trades_count,
    execution_mode = EXCLUDED.execution_mode,
    updated_at     = NOW();
"""

VERIFY_SQL = """
SELECT c.strategy_id, COUNT(*) AS positions, SUM(c.capital) AS used_capital
FROM consumption.portfolio_positions_current c
WHERE c.execution_mode = 'PAPER_TRADING' AND c.status = 'ACTIVE'
GROUP BY c.strategy_id
ORDER BY c.strategy_id;
"""


def run():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(DELETE_STALE_SQL)
    deleted = cur.rowcount
    print(f"🧹 deleted {deleted} stale PAPER_TRADING row(s) with no open ledger position")

    cur.execute(UPSERT_SQL)
    upserted = cur.rowcount
    print(f"✅ upserted {upserted} paper position row(s) from gold.paper_trades_synthetic")

    cur.execute(VERIFY_SQL)
    rows = cur.fetchall()
    print(f"📊 portfolio_positions_current PAPER_TRADING ACTIVE: {len(rows)} strategies")
    for sid, positions, used in rows:
        print(f"   {sid}: {positions} positions, used={float(used):,.2f}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    run()
