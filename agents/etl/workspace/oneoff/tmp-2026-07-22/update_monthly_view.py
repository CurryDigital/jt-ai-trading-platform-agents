#!/usr/bin/env python3
###############################################################################
# DANGER — DEPRECATED
# This script drops consumption.performance_monthly_returns and recreates it as
# a grouped VIEW. That breaks the daily ETL writers, which INSERT/UPSERT into the
# table (see agents/etl/consumption/performance/performance_strategy_results.py
# and agents/etl/consumption/portfolio/portfolio_performance_attribution.py).
# It caused Pipeline A to fail on 2026-07-24 with:
#   "cannot insert into view performance_monthly_returns"
# DO NOT RUN without first confirming the target must be a view and coordinating
# a corresponding ETL change. For history only.
###############################################################################

import sys, os
sys.path.insert(0, 'shared/scripts')
from db import get_connection

conn = get_connection()

# Rebuild the monthly returns view from ...
cur = conn.cursor()

cur.execute("""
    DROP VIEW IF EXISTS consumption."Performance_Monthly_Returns" CASCADE;
    DROP VIEW IF EXISTS consumption.performance_monthly_returns CASCADE;
    CREATE OR REPLACE VIEW consumption.performance_monthly_returns AS
    SELECT
        te.strategy_id,
        'PAPER'::text AS portfolio_type,
        EXTRACT(YEAR FROM te.executed_at)::int AS year,
        EXTRACT(MONTH FROM te.executed_at)::int AS month,
        COALESCE(SUM(te.pnl), 0) AS total_pnl,
        CASE
            WHEN MAX(r.assigned_capital) IS NOT NULL AND MAX(r.assigned_capital) > 0
            THEN (COALESCE(SUM(te.pnl), 0) / MAX(r.assigned_capital)) * 100
            ELSE NULL
        END AS return_pct
    FROM gold.trade_executions te
    LEFT JOIN gold.strategy_registry r ON r.strategy_id = te.strategy_id
    WHERE te.pnl IS NOT NULL
    GROUP BY te.strategy_id, EXTRACT(YEAR FROM te.executed_at), EXTRACT(MONTH FROM te.executed_at)
""")
conn.commit()
conn.close()
print("View updated with portfolio_type")
