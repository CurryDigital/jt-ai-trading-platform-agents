#!/usr/bin/env python3
"""
quality.py — one provenance vocabulary shared by both agents.

Principle 1 of docs/PIPELINE_DESIGN.md ("honest by construction"): every
metric/row that can reach the frontend carries where it came from, so an
estimate or a synthetic fill can never be mistaken for a measurement. This
module is the single place those values are defined, so etl and signals
can't drift into different spellings.

Paired with migration 009, which adds the columns and CHECK constraints:
  gold.strategy_ticker_scores.signal_source    ∈ SIGNAL_SOURCES
  gold.trade_executions.execution_source       ∈ EXECUTION_SOURCES
"""

# How a signal row was produced.
SIGNAL_COMPUTED = "computed"   # criteria / S9 / relative-momentum / paper runner
SIGNAL_INGESTED = "ingested"   # from a qr_research live-signals JSON file
SIGNAL_SOURCES = (SIGNAL_COMPUTED, SIGNAL_INGESTED)

# Whether a trade-execution row is a real broker fill or a synthetic/paper one.
EXEC_REAL      = "real"        # actual broker execution
EXEC_SYNTHETIC = "synthetic"   # modelled paper fill (belongs in P&L only when labeled)
EXECUTION_SOURCES = (EXEC_REAL, EXEC_SYNTHETIC)

# Whether a computed metric is measured from data or estimated by a heuristic.
METRIC_MEASURED  = "measured"
METRIC_ESTIMATED = "estimated"
METRIC_SOURCES = (METRIC_MEASURED, METRIC_ESTIMATED)


def column_exists(cur, schema: str, table: str, column: str) -> bool:
    """True if a column is present — lets a writer stamp provenance only when
    migration 009 has been applied, so the same code runs pre- and post-migration."""
    cur.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (schema, table, column),
    )
    return cur.fetchone() is not None
