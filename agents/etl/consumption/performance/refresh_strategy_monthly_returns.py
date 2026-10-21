#!/usr/bin/env python3
"""Consumption: per-strategy monthly returns keyed by strategy_id.

Reads from: gold.strategy_backtest_monthly_returns
Writes to:  consumption.strategy_monthly_returns (view)

Credentials are loaded from /home/ubuntu/.env via OPENCLAW_DATABASE_URL.

Contract (t_d152898f): return_pct is a decimal fraction portfolio-level
monthly return from the research backtest engine's own portfolio series
(or a verified single-position trade-log reconstruction), verified at
ingest to compound to returns_oos over the run OOS window. No unweighted
SUM(pnl_pct) aggregation and no unit sniffing — see
gold/strategy/refresh_strategy_monthly_returns_gold.py.

The backend route get_strategy_evaluation() queries this view by
strategy_id; the detail UI multiplies by 100 and compounds YTD.
"""

import logging
import os

import psycopg2
from dotenv import load_dotenv

load_dotenv("/home/ubuntu/.env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

# DROP+CREATE (not OR REPLACE): the previous view's strategy_id column was
# varchar sourced from gold.strategy_backtest_trades; keep the same exposed
# types via explicit casts.
DDL = """
DROP VIEW IF EXISTS consumption.strategy_monthly_returns;

CREATE VIEW consumption.strategy_monthly_returns AS
SELECT strategy_id::varchar AS strategy_id,
       year::int            AS year,
       month::int           AS month,
       ROUND(return_pct, 6) AS return_pct,
       NULL::numeric        AS benchmark_return_pct,
       NULL::numeric        AS excess_return_pct
FROM gold.strategy_backtest_monthly_returns;
"""

SMOKE = """
SELECT strategy_id,
       COUNT(*) AS rows,
       ROUND(MIN(return_pct), 6) AS min,
       ROUND(MAX(return_pct), 6) AS max,
       ROUND(AVG(return_pct), 6) AS avg
FROM consumption.strategy_monthly_returns
GROUP BY strategy_id
ORDER BY strategy_id;
"""


def get_dsn():
    dsn = os.environ.get("OPENCLAW_DATABASE_URL")
    if not dsn:
        raise RuntimeError("OPENCLAW_DATABASE_URL not set in /home/ubuntu/.env")
    if dsn.endswith("/airtrading"):
        dsn = dsn.replace("/airtrading", "/aitrading")
    return dsn


def main():
    conn = psycopg2.connect(get_dsn())
    conn.autocommit = True
    cur = conn.cursor()
    try:
        cur.execute(DDL)
        logger.info("Created view consumption.strategy_monthly_returns")

        cur.execute(
            "SELECT COUNT(DISTINCT strategy_id), COUNT(*) FROM consumption.strategy_monthly_returns"
        )
        distinct, total = cur.fetchone()
        logger.info("View has %d strategy-month rows across %d strategies", total, distinct)

        cur.execute(SMOKE)
        logger.info("Smoke sample (strategy rows min max avg):")
        for row in cur.fetchall():
            logger.info("  %s rows=%s min=%s max=%s avg=%s", *row)
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
