#!/usr/bin/env python3
"""
check_criteria_columns.py — fail if any BUY criterion references a
gold.kpis_metrics column that is mostly NULL, so it can never fire.

ROADMAP G3 / PIPELINE_DESIGN principle 4 (freshness/emptiness must be visible).
build_strategy_scores.py already refuses criteria that name a column that does
NOT EXIST. But the bug that actually shipped was subtler: macd_histogram (and
macd_signal) EXISTED but were NULL on every row, so `macd_histogram >= 0.1`
silently evaluated NULL → never matched → S9 (and cond_macd_bullish,
s012_tech_momentum) sat at all-HOLD for months with nobody able to tell "no
setup today" from "column is dead". This check turns that into a loud failure.

For each distinct BUY criterion_name (resolving the synthetic prev_* shadows to
their real column), it measures the NULL fraction over the rows the scorer
actually evaluates — the latest gold.kpis_metrics row per ticker — and flags any
column that is > THRESHOLD NULL.

Needs DB access (reads gold.kpis_metrics + gold.strategy_signal_criteria). This
is NOT part of the DB-free CI gate; run it against prod after a refresh:
    python3 tools/check_criteria_columns.py            # exit 1 if any dead column
    python3 tools/check_criteria_columns.py --threshold 0.8
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, ".."))
sys.path.insert(0, os.path.join(_REPO, "agents", "etl", "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

# Keep in sync with build_strategy_scores.SYNTHETIC_PREV_COLUMNS — synthetic
# criterion names the scorer computes from a real column's prior-row value.
SYNTHETIC_PREV_COLUMNS = {
    "prev_macd_histogram": "macd_histogram",
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--threshold", type=float, default=0.5,
                   help="flag a column NULL on more than this fraction of latest rows (default 0.5)")
    args = p.parse_args()

    from db import get_connection
    conn = get_connection()
    cur = conn.cursor()

    # Real gold.kpis_metrics columns.
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_schema='gold' AND table_name='kpis_metrics'
    """)
    real_cols = {r[0] for r in cur.fetchall()}

    # Distinct BUY criteria, resolved to the real column they read.
    cur.execute("""
        SELECT DISTINCT criterion_name FROM gold.strategy_signal_criteria
        WHERE signal_type = 'buy'
    """)
    referenced = {}
    for (name,) in cur.fetchall():
        real = SYNTHETIC_PREV_COLUMNS.get(name, name)
        referenced.setdefault(real, set()).add(name)

    # Only real, existing columns can be NULL-measured. Non-existent columns are
    # already caught (loudly) by build_strategy_scores.SQL_UNKNOWN_CRITERIA.
    measurable = {c: refs for c, refs in referenced.items() if c in real_cols}
    if not measurable:
        print("✅ no BUY criteria reference measurable kpis_metrics columns (nothing to check)")
        conn.close()
        return 0

    # NULL fraction over the latest row per ticker — exactly the population
    # build_strategy_scores evaluates.
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT DISTINCT ON (ticker) ticker FROM gold.kpis_metrics
            ORDER BY ticker, date DESC
        ) t
    """)
    n_tickers = cur.fetchone()[0] or 0
    if n_tickers == 0:
        print("⚠️  gold.kpis_metrics has no rows — cannot assess criterion columns")
        conn.close()
        return 0

    dead = []
    print(f"criterion columns over {n_tickers} latest-per-ticker rows "
          f"(threshold {args.threshold:.0%} NULL):")
    for col in sorted(measurable):
        cur.execute(f"""
            SELECT COUNT(*) FILTER (WHERE v.{col} IS NULL)
            FROM (
                SELECT DISTINCT ON (ticker) * FROM gold.kpis_metrics
                ORDER BY ticker, date DESC
            ) v
        """)
        n_null = cur.fetchone()[0] or 0
        frac = n_null / n_tickers
        refs = ", ".join(sorted(measurable[col]))
        flag = "❌" if frac > args.threshold else "  "
        print(f"  {flag} {col:<28} {frac:6.1%} NULL   (criteria: {refs})")
        if frac > args.threshold:
            dead.append((col, frac, refs))

    conn.close()
    if dead:
        print(f"\n❌ {len(dead)} criterion column(s) are mostly NULL — those BUY criteria "
              f"can never fire (all-HOLD). Fix the upstream builder or drop the criterion.")
        return 1
    print("\n✅ every BUY criterion references a populated column")
    return 0


if __name__ == "__main__":
    sys.exit(main())
