#!/usr/bin/env python3
"""
Refresh gold.paper_trades_synthetic from consumption.signal_logs.

This backfills synthetic paper trades for approved pipeline strategies
that are not yet wired to the real paper execution agent. Run after the
daily signal ingestion completes.

APPEND-ONLY WRITER CONTRACT (t_1b373785, 2026-10-26; spec:
paper_feeder_append_only_spec.md attached to t_47a76ea3)
--------------------------------------------------------
This feeder follows the platform append-only ledger contract:
- NEVER DELETE from gold.paper_trades_synthetic. NEVER UPDATE entry-side
  columns (ticker, direction, entry_date, entry_price, n_shares,
  signal_weight, assigned_capital, run_id, first_seen_at).
- ONE uuid4 run_id per refresh run: stamped as run_id/first_seen_at on new
  rows and as exit_run_id/exit_updated_at on rows this run CLOSES.
- Upsert on identity key (strategy_id, ticker, entry_date) via
  uniq_pts_strategy_ticker_entry: ON CONFLICT DO UPDATE of exit fields only,
  WHERE status='open' — closed rows are FROZEN.
- Restatement alarm: a stored row whose entry-side differs from this run's
  recomputation is left untouched and counted in entry_mismatches (tickers
  named in the audit-row notes). Upstream restatement must surface, never
  silently rewrite history.
- Orphans: rows previously written for a REFRESHED strategy but not
  reproduced by this run's replay are LEFT UNTOUCHED and counted in
  rows_orphaned. Counting is scoped to the strategies refreshed this run —
  rows for strategies outside the refresh scope (e.g. dynamic-scoring
  strategies owned by rebuild_paper_positions.py, or C1 with
  disable_paper_rebuild) are never counted as orphans.
- ONE gold.paper_feeder_runs audit row per run (feeder=
  'refresh_paper_trades_synthetic', strategy_id='ALL'), committed in the
  same transaction as the ledger writes.

Open-row mark-to-market: this generator historically stores the latest mark
(exit_date=latest price date, exit_price=latest close, pnl/pnl_pct marked)
on OPEN rows. That behaviour is preserved as an exit-side mark UPDATE on
conflicting open rows; exit_run_id/exit_updated_at stay reserved for true
closes so reconstruction semantics (spec section 3) keep their meaning.

DESIGN NOTE: Dynamic scoring strategies
Strategies that have a live scoring engine (rows in gold.strategy_ticker_scores)
are managed by rebuild_paper_positions.py. This script skips them so it does
not overwrite the position-aware rebalancer output with stale signal_logs data.
Both writers key rows by (strategy_id, ticker, entry_date); rebuild only
INSERTs new opens / UPDATEs exit-side on close in normal operation, so the
identity key stays collision-free across writers.

DESIGN NOTE: CASH handling
- CASH is a portfolio cash-bucket placeholder, not a tradeable ticker. It is
  excluded from ticker-level tables; 100% cash is represented implicitly by
  the absence of security positions in this table.
"""
import hashlib
import json
import os
import subprocess
import uuid

import psycopg2
from dotenv import load_dotenv

load_dotenv(os.path.expanduser("~/.hermes/profiles/qr_etl/env/etl.env"))

FEEDER = "refresh_paper_trades_synthetic"
TABLE = "gold.paper_trades_synthetic"  # overridable for rollback tests


def get_conn():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        port=os.getenv("DB_PORT", "5432"),
    )


def script_sha256():
    with open(os.path.abspath(__file__), "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def git_sha():
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True, text=True, timeout=10,
        )
        if out.returncode != 0:
            return None
        return out.stdout.strip() or None
    except Exception:
        return None


SQL_FETCH_SCOPE = """
SELECT id FROM gold.v_pipeline_ui_feed
WHERE id NOT IN (SELECT DISTINCT strategy_id FROM gold.strategy_ticker_scores)
ORDER BY id
"""

# Schema guard: the append-only migration (2026-10-26_paper_feeder_append_only.sql)
# must be live before this writer runs. Fail loudly instead of degrading.
SQL_SCHEMA_GUARD = """
SELECT
  (SELECT count(*) FROM information_schema.columns
   WHERE table_schema='gold' AND table_name='paper_trades_synthetic'
     AND column_name IN ('run_id','first_seen_at','exit_run_id','exit_updated_at')) AS cols,
  (SELECT count(*) FROM pg_indexes
   WHERE schemaname='gold' AND tablename='paper_trades_synthetic'
     AND indexname='uniq_pts_strategy_ticker_entry') AS ident_idx,
  (SELECT to_regclass('gold.paper_feeder_runs') IS NOT NULL) AS audit_tbl
"""

# Closed-trade candidates: pair consecutive signals per (strategy, ticker).
# CASH is excluded: it is a portfolio cash-bucket placeholder, not a ticker.
# (Same pairing/sizing logic as the legacy rebuild; scope now passed as a
# parameter so candidate generation and orphan counting can never drift.)
SQL_BUILD_CAND_CLOSED = """
CREATE TEMP TABLE _cand_closed ON COMMIT DROP AS
WITH signals AS (
    SELECT DISTINCT ON (strategy_id, signal_date, ticker)
        strategy_id,
        signal_date,
        ticker,
        signal_type,
        CASE
            WHEN signal_criteria LIKE '{%%}' THEN (signal_criteria::jsonb->>'weight')::numeric
            WHEN signal_criteria LIKE 'weight=%%' THEN split_part(split_part(signal_criteria, ';', 1), '=', 2)::numeric
            ELSE NULL::numeric
        END AS weight
    FROM consumption.signal_logs
    WHERE strategy_id = ANY(%(scope)s)
      AND ticker != 'CASH'
    ORDER BY strategy_id, signal_date, ticker, logged_at DESC
),
strategy_capital AS (
    SELECT strategy_id, assigned_capital FROM gold.strategy_registry
    WHERE strategy_id = ANY(%(scope)s)
),
signal_pairs AS (
    SELECT
        s.strategy_id,
        s.signal_date AS entry_date,
        s.ticker,
        s.signal_type,
        s.weight,
        LEAD(s.signal_date) OVER (PARTITION BY s.strategy_id, s.ticker ORDER BY s.signal_date) AS next_signal_date,
        sc.assigned_capital
    FROM signals s
    JOIN strategy_capital sc ON sc.strategy_id = s.strategy_id
),
entry_prices AS (
    SELECT DISTINCT ON (sp.strategy_id, sp.ticker, sp.entry_date)
        sp.strategy_id, sp.ticker, sp.entry_date,
        p.close AS entry_price
    FROM signal_pairs sp
    LEFT JOIN silver.unified_prices p ON p.ticker = sp.ticker AND p.date <= sp.entry_date
    ORDER BY sp.strategy_id, sp.ticker, sp.entry_date, p.date DESC
),
exit_prices AS (
    SELECT DISTINCT ON (sp.strategy_id, sp.ticker, sp.next_signal_date)
        sp.strategy_id, sp.ticker, sp.next_signal_date AS exit_date,
        p.close AS exit_price
    FROM signal_pairs sp
    LEFT JOIN silver.unified_prices p ON p.ticker = sp.ticker AND p.date <= sp.next_signal_date
    WHERE sp.next_signal_date IS NOT NULL
    ORDER BY sp.strategy_id, sp.ticker, sp.next_signal_date, p.date DESC
),
-- Lot sizing (DECISION 2026-08-17, t_928a4e7d,
-- docs/decisions/2026-08-17_lot_convention.md): US-listed equities/ETFs
-- size in WHOLE SHARES (lot = 1) — IBKR supports fractional US shares,
-- so 1 share is conservative-realistic and matches strategy slot math.
-- HK tickers use silver.asset_registry.lot_size when populated
-- (fallback 1 = no rounding until board lots are loaded); SG (.SI)
-- uses SGX board lot 100 (registry override when populated); futures
-- ('=' in ticker) are not lot-rounded. Positions that cannot afford
-- one lot are skipped.
sized AS (
    SELECT
        sp.strategy_id, sp.ticker, sp.signal_type, sp.entry_date, sp.next_signal_date,
        sp.weight, sp.assigned_capital, ep.entry_price,
        CASE
            WHEN sp.ticker LIKE '%%.HK' THEN COALESCE(NULLIF(ar.lot_size, 0), 1)
            WHEN POSITION('=' IN sp.ticker) > 0 THEN 1
            WHEN sp.ticker LIKE '%%.SI' THEN COALESCE(NULLIF(ar.lot_size, 0), 100)
            ELSE COALESCE(NULLIF(ar.lot_size, 0), 1)
        END AS lot,
        CASE WHEN ep.entry_price > 0 AND sp.weight IS NOT NULL AND sp.assigned_capital IS NOT NULL
             THEN (sp.weight * sp.assigned_capital) / ep.entry_price END AS raw_shares
    FROM signal_pairs sp
    JOIN entry_prices ep ON ep.strategy_id = sp.strategy_id AND ep.ticker = sp.ticker AND ep.entry_date = sp.entry_date
    LEFT JOIN silver.asset_registry ar ON ar.ticker = sp.ticker
)
SELECT
    s.strategy_id, s.ticker,
    CASE WHEN s.signal_type = 'BUY' THEN 'long' ELSE 'short' END AS direction,
    s.entry_date, s.next_signal_date AS exit_date, s.entry_price, xp.exit_price,
    FLOOR(s.raw_shares / s.lot) * s.lot AS n_shares,
    (xp.exit_price - s.entry_price) * (FLOOR(s.raw_shares / s.lot) * s.lot)
         * CASE WHEN s.signal_type = 'BUY' THEN 1 ELSE -1 END AS pnl,
    ((xp.exit_price - s.entry_price) / s.entry_price) * 100
         * CASE WHEN s.signal_type = 'BUY' THEN 1 ELSE -1 END AS pnl_pct,
    'closed' AS status, s.weight AS signal_weight, s.assigned_capital
FROM sized s
JOIN exit_prices xp ON xp.strategy_id = s.strategy_id AND xp.ticker = s.ticker AND xp.exit_date = s.next_signal_date
WHERE s.raw_shares IS NOT NULL
  AND FLOOR(s.raw_shares / s.lot) * s.lot > 0
  -- t_8b58b2bc: never write same-day closed rows. entry=exit at the same
  -- close yields $0 PnL artifacts that corrupt WR/PF (memo 2026-08-17
  -- section 2.3). A signal paired with itself on one date is not a trade.
  AND s.next_signal_date > s.entry_date
"""

# Open-trade candidates: the latest unclosed signal per (strategy, ticker),
# marked to the latest available close (legacy mark-to-market behaviour).
SQL_BUILD_CAND_OPEN = """
CREATE TEMP TABLE _cand_open ON COMMIT DROP AS
WITH signals AS (
    SELECT DISTINCT ON (strategy_id, signal_date, ticker)
        strategy_id, signal_date, ticker, signal_type,
        CASE
            WHEN signal_criteria LIKE '{%%}' THEN (signal_criteria::jsonb->>'weight')::numeric
            WHEN signal_criteria LIKE 'weight=%%' THEN split_part(split_part(signal_criteria, ';', 1), '=', 2)::numeric
            ELSE NULL::numeric
        END AS weight
    FROM consumption.signal_logs
    WHERE strategy_id = ANY(%(scope)s)
      AND ticker != 'CASH'
    ORDER BY strategy_id, signal_date, ticker, logged_at DESC
),
last_signals AS (
    SELECT DISTINCT ON (strategy_id, ticker) strategy_id, ticker, signal_date AS entry_date, signal_type, weight
    FROM signals ORDER BY strategy_id, ticker, signal_date DESC
),
strategy_capital AS (
    SELECT strategy_id, assigned_capital FROM gold.strategy_registry
    WHERE strategy_id = ANY(%(scope)s)
),
entry_prices AS (
    SELECT DISTINCT ON (ls.strategy_id, ls.ticker, ls.entry_date)
        ls.strategy_id, ls.ticker, ls.entry_date,
        p.close AS entry_price
    FROM last_signals ls
    LEFT JOIN silver.unified_prices p ON p.ticker = ls.ticker AND p.date <= ls.entry_date
    ORDER BY ls.strategy_id, ls.ticker, ls.entry_date, p.date DESC
),
latest_prices AS (
    SELECT ticker, price_date, latest_price FROM (
        SELECT DISTINCT ON (ticker) ticker, date AS price_date, close AS latest_price
        FROM silver.unified_prices WHERE close IS NOT NULL ORDER BY ticker, date DESC
    ) real_prices
),
-- Lot sizing: same convention as the closed-trade candidates above
-- (DECISION 2026-08-17, t_928a4e7d).
sized AS (
    SELECT
        ls.strategy_id, ls.ticker, ls.signal_type, ls.entry_date, ls.weight,
        sc.assigned_capital, ep.entry_price,
        CASE
            WHEN ls.ticker LIKE '%%.HK' THEN COALESCE(NULLIF(ar.lot_size, 0), 1)
            WHEN POSITION('=' IN ls.ticker) > 0 THEN 1
            WHEN ls.ticker LIKE '%%.SI' THEN COALESCE(NULLIF(ar.lot_size, 0), 100)
            ELSE COALESCE(NULLIF(ar.lot_size, 0), 1)
        END AS lot,
        CASE WHEN ep.entry_price > 0 AND ls.weight IS NOT NULL AND sc.assigned_capital IS NOT NULL
             THEN (ls.weight * sc.assigned_capital) / ep.entry_price END AS raw_shares
    FROM last_signals ls
    JOIN strategy_capital sc ON sc.strategy_id = ls.strategy_id
    JOIN entry_prices ep ON ep.strategy_id = ls.strategy_id AND ep.ticker = ls.ticker AND ep.entry_date = ls.entry_date
    LEFT JOIN silver.asset_registry ar ON ar.ticker = ls.ticker
)
SELECT
    s.strategy_id, s.ticker,
    CASE WHEN s.signal_type = 'BUY' THEN 'long' ELSE 'short' END AS direction,
    s.entry_date, lp.price_date AS exit_date, s.entry_price, lp.latest_price AS exit_price,
    FLOOR(s.raw_shares / s.lot) * s.lot AS n_shares,
    CASE WHEN lp.latest_price IS NOT NULL
         THEN (lp.latest_price - s.entry_price) * (FLOOR(s.raw_shares / s.lot) * s.lot)
              * CASE WHEN s.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END AS pnl,
    CASE WHEN lp.latest_price IS NOT NULL
         THEN ((lp.latest_price - s.entry_price) / s.entry_price) * 100
              * CASE WHEN s.signal_type = 'BUY' THEN 1 ELSE -1 END ELSE NULL END AS pnl_pct,
    'open' AS status, s.weight AS signal_weight, s.assigned_capital
FROM sized s
LEFT JOIN latest_prices lp ON lp.ticker = s.ticker
WHERE s.raw_shares IS NOT NULL
  AND FLOOR(s.raw_shares / s.lot) * s.lot > 0
"""


def sql_orphans(table):
    # Rows previously written for a strategy refreshed THIS run but not
    # reproduced by this run's replay. Scoped per refreshed strategy: rows
    # owned by other writers/scopes are never counted.
    return f"""
SELECT p.strategy_id, p.ticker, p.entry_date
FROM {table} p
WHERE p.strategy_id = ANY(%(scope)s)
  AND NOT EXISTS (
      SELECT 1 FROM _cand_closed c
      WHERE c.strategy_id = p.strategy_id AND c.ticker IS NOT DISTINCT FROM p.ticker AND c.entry_date = p.entry_date
  )
  AND NOT EXISTS (
      SELECT 1 FROM _cand_open c
      WHERE c.strategy_id = p.strategy_id AND c.ticker IS NOT DISTINCT FROM p.ticker AND c.entry_date = p.entry_date
  )
"""


def sql_entry_mismatches(table):
    # Restatement alarm: stored entry-side differs from this run's replay.
    # Entry-side is immutable — the row is left untouched and reported.
    return f"""
SELECT p.strategy_id, p.ticker, p.entry_date,
       p.entry_price AS stored_entry_price, c.entry_price AS replay_entry_price,
       p.n_shares AS stored_n_shares, c.n_shares AS replay_n_shares,
       p.direction AS stored_direction, c.direction AS replay_direction
FROM (
    SELECT * FROM _cand_closed
    UNION ALL
    SELECT * FROM _cand_open
) c
JOIN {table} p
  ON p.strategy_id = c.strategy_id
 AND p.ticker IS NOT DISTINCT FROM c.ticker
 AND p.entry_date = c.entry_date
WHERE p.entry_price IS DISTINCT FROM c.entry_price
   OR p.n_shares    IS DISTINCT FROM c.n_shares
   OR p.direction   IS DISTINCT FROM c.direction
"""


def sql_drop_mismatched_candidates_closed(table):
    # Mismatched candidates are removed from BOTH candidate tables so the
    # upserts below can never touch the stored row (not even exit-side).
    return f"""
DELETE FROM _cand_closed c
USING {table} p
WHERE p.strategy_id = c.strategy_id
  AND p.ticker IS NOT DISTINCT FROM c.ticker
  AND p.entry_date = c.entry_date
  AND (p.entry_price IS DISTINCT FROM c.entry_price
       OR p.n_shares IS DISTINCT FROM c.n_shares
       OR p.direction IS DISTINCT FROM c.direction)
"""


def sql_drop_mismatched_candidates_open(table):
    return f"""
DELETE FROM _cand_open c
USING {table} p
WHERE p.strategy_id = c.strategy_id
  AND p.ticker IS NOT DISTINCT FROM c.ticker
  AND p.entry_date = c.entry_date
  AND (p.entry_price IS DISTINCT FROM c.entry_price
       OR p.n_shares IS DISTINCT FROM c.n_shares
       OR p.direction IS DISTINCT FROM c.direction)
"""


def sql_upsert_closed(table):
    # New closed rows: run_id/first_seen_at stamped, exit_run_id/exit_updated_at
    # stamped (they are born closed). Existing OPEN rows at the identity key are
    # closed in place (exit-side only). CLOSED rows are FROZEN by the WHERE.
    return f"""
INSERT INTO {table}
    (strategy_id, ticker, direction, entry_date, exit_date, entry_price, exit_price,
     n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital,
     run_id, first_seen_at, exit_run_id, exit_updated_at, updated_at)
SELECT
    strategy_id, ticker, direction, entry_date, exit_date, entry_price, exit_price,
    n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital,
    %(run_id)s, now(), %(run_id)s, now(), now()
FROM _cand_closed
ON CONFLICT (strategy_id, ticker, entry_date) DO UPDATE SET
    exit_date       = EXCLUDED.exit_date,
    exit_price      = EXCLUDED.exit_price,
    pnl             = EXCLUDED.pnl,
    pnl_pct         = EXCLUDED.pnl_pct,
    status          = EXCLUDED.status,
    exit_run_id     = EXCLUDED.exit_run_id,
    exit_updated_at = now(),
    updated_at      = now()
WHERE {table}.status = 'open'
RETURNING (xmax = 0) AS was_inserted
"""


def sql_upsert_open(table):
    # New open rows: run_id/first_seen_at stamped; exit_run_id/exit_updated_at
    # NULL (exit cols carry the current MARK, not a close). Existing open rows
    # get a mark-to-market refresh of exit fields + updated_at only —
    # exit_run_id/exit_updated_at stay reserved for true closes. CLOSED rows
    # at the identity key are FROZEN (candidate dropped by the WHERE).
    return f"""
INSERT INTO {table}
    (strategy_id, ticker, direction, entry_date, exit_date, entry_price, exit_price,
     n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital,
     run_id, first_seen_at, exit_run_id, exit_updated_at, updated_at)
SELECT
    strategy_id, ticker, direction, entry_date, exit_date, entry_price, exit_price,
    n_shares, pnl, pnl_pct, status, signal_weight, assigned_capital,
    %(run_id)s, now(), NULL, NULL, now()
FROM _cand_open
ON CONFLICT (strategy_id, ticker, entry_date) DO UPDATE SET
    exit_date  = EXCLUDED.exit_date,
    exit_price = EXCLUDED.exit_price,
    pnl        = EXCLUDED.pnl,
    pnl_pct    = EXCLUDED.pnl_pct,
    updated_at = now()
WHERE {table}.status = 'open'
RETURNING (xmax = 0) AS was_inserted
"""


SQL_INSERT_AUDIT = """
INSERT INTO gold.paper_feeder_runs
    (run_id, feeder, strategy_id, rows_considered, rows_inserted, rows_closed,
     rows_orphaned, entry_mismatches, script_sha256, git_sha, params, notes)
VALUES
    (%(run_id)s, %(feeder)s, 'ALL', %(considered)s, %(inserted)s, %(closed)s,
     %(orphaned)s, %(mismatches)s, %(sha)s, %(git)s, %(params)s::jsonb, %(notes)s)
"""


def refresh():
    conn = get_conn()
    try:
        conn.autocommit = False
        c = conn.cursor()

        c.execute(SQL_SCHEMA_GUARD)
        cols, ident_idx, audit_tbl = c.fetchone()
        if cols != 4 or ident_idx != 1 or not audit_tbl:
            raise RuntimeError(
                "append-only schema not live "
                f"(cols={cols}/4, uniq_pts_strategy_ticker_entry={ident_idx}, "
                f"paper_feeder_runs={audit_tbl}); run migration "
                "2026-10-26_paper_feeder_append_only.sql first")

        run_id = str(uuid.uuid4())

        c.execute(SQL_FETCH_SCOPE)
        scope = [r[0] for r in c.fetchall()]
        print(f"Refresh scope: {len(scope)} strategies "
              f"(v_pipeline_ui_feed minus strategy_ticker_scores)")

        params = {"scope": scope}
        c.execute(SQL_BUILD_CAND_CLOSED, params)
        c.execute(SQL_BUILD_CAND_OPEN, params)

        c.execute("SELECT count(*) FROM _cand_closed")
        n_closed_cand = c.fetchone()[0]
        c.execute("SELECT count(*) FROM _cand_open")
        n_open_cand = c.fetchone()[0]
        considered = n_closed_cand + n_open_cand

        # Orphans (counted BEFORE mismatch removal: a mismatched row WAS
        # reproduced by the replay, it is a restatement, not an orphan).
        c.execute(sql_orphans(TABLE), params)
        orphans = c.fetchall()

        # Restatement alarm.
        c.execute(sql_entry_mismatches(TABLE))
        mismatches = c.fetchall()
        if mismatches:
            c.execute(sql_drop_mismatched_candidates_closed(TABLE))
            c.execute(sql_drop_mismatched_candidates_open(TABLE))

        # Upserts. RETURNING (xmax = 0): True = brand-new identity key.
        c.execute(sql_upsert_closed(TABLE), {"run_id": run_id})
        closed_ret = [r[0] for r in c.fetchall()]
        inserted = sum(1 for x in closed_ret if x)
        rows_closed = sum(1 for x in closed_ret if not x)  # open -> closed

        c.execute(sql_upsert_open(TABLE), {"run_id": run_id})
        open_ret = [r[0] for r in c.fetchall()]
        inserted += sum(1 for x in open_ret if x)
        marks = sum(1 for x in open_ret if not x)  # mark-to-market refreshes
        dropped_frozen = considered - len(mismatches) \
            - len(closed_ret) - len(open_ret)

        notes_parts = []
        if mismatches:
            tickers = sorted({f"{m[0]}/{m[1]}" for m in mismatches})
            notes_parts.append(
                f"entry_mismatches (restatement, rows untouched): {', '.join(tickers)}")
        if dropped_frozen:
            notes_parts.append(
                f"{dropped_frozen} candidate(s) dropped: frozen closed row at identity key")
        if orphans:
            notes_parts.append(
                f"orphans left untouched: "
                + ", ".join(sorted(f"{o[0]}/{o[1]}/{o[2]}" for o in orphans[:20]))
                + (" ..." if len(orphans) > 20 else ""))
        notes = " | ".join(notes_parts) if notes_parts else None

        c.execute(SQL_INSERT_AUDIT, {
            "run_id": run_id,
            "feeder": FEEDER,
            "considered": considered,
            "inserted": inserted,
            "closed": rows_closed,
            "orphaned": len(orphans),
            "mismatches": len(mismatches),
            "sha": script_sha256(),
            "git": git_sha(),
            "params": json.dumps({
                "strategies_refreshed": scope,
                "scope_source": "v_pipeline_ui_feed minus strategy_ticker_scores",
                "open_mark_refreshes": marks,
            }),
            "notes": notes,
        })

        conn.commit()
        c.close()
        print(f"run_id={run_id} considered={considered} inserted={inserted} "
              f"closed={rows_closed} marks={marks} orphaned={len(orphans)} "
              f"entry_mismatches={len(mismatches)}")
        print("paper_trades_synthetic refreshed (append-only)")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    refresh()
