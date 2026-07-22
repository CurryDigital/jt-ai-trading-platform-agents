#!/usr/bin/env python3
"""
Generate and apply migration to add annual_pnl_2024/2025/2026 to gold.v_pipeline_ui_feed.
Uses the current DB view definition as the base so we don't clobber live_metrics changes.
Adds new columns at the end of the view's SELECT list so CREATE OR REPLACE VIEW succeeds.
"""
import os
import re
import sys

ETL_HOME = os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl')
SHARED = os.path.join(ETL_HOME, 'shared', 'scripts')
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

from db import get_connection  # noqa: E402

MIGRATION_PATH = os.path.join(ETL_HOME, 'migrations', '2026-07-20_v_pipeline_ui_feed_add_annual_pnl_2024.sql')


def add_annual_pnl_to_viewdef(viewdef: str) -> str:
    # Add annual_pnl columns to latest_backtest CTE select list (CTE order is flexible)
    backtest_select = re.search(
        r'(SELECT DISTINCT ON \(strategy_backtest_runs\.strategy_id\)\s+strategy_backtest_runs\.strategy_id,\s+)',
        viewdef,
    )
    if not backtest_select:
        raise RuntimeError('Could not locate latest_backtest SELECT')
    insert_after = backtest_select.end()
    viewdef = (
        viewdef[:insert_after]
        + "strategy_backtest_runs.annual_pnl_2024,\n            strategy_backtest_runs.annual_pnl_2025,\n            strategy_backtest_runs.annual_pnl_2026,\n            "
        + viewdef[insert_after:]
    )

    # Add annual_pnl columns to published CTE before its FROM clause, with a leading comma
    published_from = re.search(
        r"(\s+FROM gold\.strategy_registry r\s+JOIN gold\.strategy_research res ON res\.strategy_id::text = r\.strategy_id::text\s+LEFT JOIN latest_backtest b ON b\.strategy_id::text = r\.strategy_id::text\s+LEFT JOIN latest_ticker_score lts ON lts\.strategy_id::text = r\.strategy_id::text\s*)",
        viewdef,
    )
    if not published_from:
        raise RuntimeError('Could not locate published FROM clause')
    insert_before = published_from.start()
    viewdef = (
        viewdef[:insert_before]
        + ",\n       b.annual_pnl_2024,\n       b.annual_pnl_2025,\n       b.annual_pnl_2026\n"
        + viewdef[insert_before:]
    )

    # Add annual_pnl columns at the end of the final SELECT list (before FROM), with a leading comma
    final_from = re.search(
        r"(\s+FROM published s\s+LEFT JOIN live_metrics lm ON lm\.strategy_id = s\.strategy_id::text\s+WHERE s\.publishable\s+ORDER BY)",
        viewdef,
    )
    if not final_from:
        raise RuntimeError('Could not locate final FROM clause')
    insert_before = final_from.start()
    viewdef = (
        viewdef[:insert_before]
        + ",\n       s.annual_pnl_2024 * 100::numeric AS annual_pnl_2024,\n       s.annual_pnl_2025 * 100::numeric AS annual_pnl_2025,\n       s.annual_pnl_2026 * 100::numeric AS annual_pnl_2026"
        + viewdef[insert_before:]
    )
    return viewdef


def main():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT pg_get_viewdef('gold.v_pipeline_ui_feed', true);")
        viewdef = cur.fetchone()[0]

        new_viewdef = add_annual_pnl_to_viewdef(viewdef)
        migration_sql = f"-- Migration: add annual_pnl_2024/2025/2026 to gold.v_pipeline_ui_feed.\n-- Generated at {os.path.basename(__file__)} from current DB view definition.\n-- Task: t_7d2e4c9a\n\nCREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS\n{new_viewdef}\n"

        with open(MIGRATION_PATH, 'w') as f:
            f.write(migration_sql)
        print(f"wrote migration: {MIGRATION_PATH}")

        cur.execute(migration_sql)
        conn.commit()
        print("applied migration to DB")
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    main()
