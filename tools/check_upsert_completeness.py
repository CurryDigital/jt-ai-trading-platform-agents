#!/usr/bin/env python3
"""
check_upsert_completeness.py — CI lint for the "partial ON CONFLICT" bug class.

Gold metric tables are recomputed from source every run and re-insert a rolling
window, so they hit ON CONFLICT for most dates. If the DO UPDATE clause refreshes
only some columns, the rest stay STALE (this is exactly how corrected indicators
failed to propagate — PIPELINE_DESIGN S1/S4). For these tables the contract is:
**every non-key inserted column must be refreshed on conflict.**

This lint is intentionally CURATED, not automatic: FULL_REFRESH_TABLES lists the
(key,date) metric tables that must fully refresh. A blanket scan is too noisy —
it can't tell a legitimate COALESCE-merge (bronze price upserts), a DELETE+INSERT
consumption view, or an intentionally-partial ledger update from a real bug. Add
a table here when you add a new full-refresh metric builder; that list is also
the documentation of "these tables recompute everything each run".

Both `col = EXCLUDED.col` and `col = COALESCE(EXCLUDED.col, ...)` count as
refreshed. Timestamp columns set to NOW() count. Run:
    python3 tools/check_upsert_completeness.py
"""
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, ".."))

# table -> the builder file that owns its full-refresh upsert
FULL_REFRESH_TABLES = {
    "gold.kpis_metrics":            "agents/etl/gold/equity/build_equity_kpis.py",
    "gold.index_metrics":           "agents/etl/gold/market/build_market_metrics.py",
    "gold.market_sentiment_daily":  "agents/etl/gold/market/build_market_metrics.py",
    "gold.crypto_kpis":             "agents/etl/gold/crypto/build_crypto_kpis.py",
    "gold.stock_metrics_history":   "agents/etl/gold/equity/build_stock_metrics_history.py",
    "gold.commodity_futures":       "agents/etl/gold/commodity/build_commodity_metrics.py",
    "gold.fx_metrics":              "agents/etl/gold/fx/build_fx_metrics.py",
    "gold.earnings_data":           "agents/etl/gold/equity/build_earnings_signals.py",
    "gold.earnings_signals":        "agents/etl/gold/equity/build_earnings_signals.py",
    "gold.sue_scores":              "agents/etl/gold/equity/build_earnings_signals.py",
}

TS_COLS = {"updated_at", "created_at", "calculated_at", "collected_at"}


def check_table(tbl, path):
    src = open(os.path.join(_REPO, path)).read()
    ins = re.search(rf"INSERT INTO\s+{re.escape(tbl)}\s*\((.*?)\)\s*\n", src, re.S)
    if not ins:
        return [f"{tbl}: no INSERT found in {path}"]
    cols = [c.strip() for c in re.sub(r"--.*", "", ins.group(1)).replace("\n", " ").split(",") if c.strip()]
    conf = re.search(r"ON CONFLICT\s*\(([^)]*)\)\s*DO UPDATE SET(.*?);", src[ins.end():], re.S)
    if not conf:
        return [f"{tbl}: no ON CONFLICT DO UPDATE in {path}"]
    key = [k.strip() for k in conf.group(1).split(",")]
    # a column is "refreshed" if it appears as `col = EXCLUDED...`, `col = COALESCE(...`, or NOW()
    refreshed = set(re.findall(r"([a-z0-9_]+)\s*=\s*(?:EXCLUDED\.|COALESCE\s*\(|NOW\s*\()", conf.group(2)))
    missing = [c for c in cols if c not in key and c not in refreshed and c not in TS_COLS]
    return [f"{tbl} ({path}): {len(missing)} column(s) not refreshed on conflict: {missing}"] if missing else []


def main() -> int:
    problems = []
    for tbl, path in sorted(FULL_REFRESH_TABLES.items()):
        if not os.path.isfile(os.path.join(_REPO, path)):
            problems.append(f"{tbl}: builder {path} not found")
            continue
        problems.extend(check_table(tbl, path))
    if problems:
        print(f"❌ {len(problems)} incomplete metric upsert(s):")
        for p in problems:
            print(f"  {p}")
        print("  → every non-key column of a full-refresh metric table must be "
              "refreshed on conflict (EXCLUDED or COALESCE(EXCLUDED,...)).")
        return 1
    print(f"✅ upsert completeness OK — {len(FULL_REFRESH_TABLES)} full-refresh metric tables verified")
    return 0


if __name__ == "__main__":
    sys.exit(main())
