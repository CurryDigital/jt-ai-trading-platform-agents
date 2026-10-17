#!/usr/bin/env python3
"""
Silver Transform: Unified Prices
Merges bronze.yf_prices + bronze.fmp_prices + bronze.manual_prices
→ silver.unified_prices (deduplicated, normalized, source-ranked)

asset_class / market provenance (2026-08-24, kanban t_ac502e22):
This script is the ONLY place silver.unified_prices.asset_class/market should
be stamped, and it sources them EXCLUSIVELY from silver.asset_registry
(master: gold.asset_registry) via LEFT JOIN on ticker. The asset registry is
the single source of truth — never hardcode class strings ('equity',
'HK Stock', ...) in writers of this table. LEFT JOIN means tickers missing
from the registry land as NULL by design (visible gap, not a silent guess).
The upsert re-stamps asset_class/market on conflict, so every run re-aligns
this table with the registry across FULL bronze history (no date filter).
gold.daily_ohlcv only mirrors the last 14 days (see gold/gold_builder.py).
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection


def _snapshot_id():
    """Full-history merge guard (user directive 2026-10-16): every run must
    carry a snapshot/run id. Scheduled pipelines get one from the runner or
    wrapper (ETL_RUN_SNAPSHOT_ID); manual restates must pass --snapshot-id
    after creating their backups."""
    for i, a in enumerate(sys.argv):
        if a == '--snapshot-id' and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return os.environ.get('SILVER_MERGE_SNAPSHOT_ID') or os.environ.get('ETL_RUN_SNAPSHOT_ID')


def _ensure_snapshot_log(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.etl_snapshot_log (
            snapshot_id text PRIMARY KEY,
            scope text NOT NULL,
            script text NOT NULL,
            pre_rows bigint,
            pre_max_date date,
            post_rows bigint,
            post_max_date date,
            note text,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)

UPSERT_SQL = """
INSERT INTO silver.unified_prices
    (ticker, asset_class, market, date, open, high, low, close, volume,
     adjusted_close, returns_1d, returns_log, source, primary_source, all_sources, updated_at)
WITH ranked AS (
    -- yfinance equities/ETFs (priority 1)
    SELECT
        ticker,
        NULL::varchar AS asset_class,
        NULL::varchar AS market,
        date,
        open::numeric(20,8),
        high::numeric(20,8),
        low::numeric(20,8),
        close::numeric(20,8),
        volume::numeric,
        adjusted_close::numeric(20,8),
        'yfinance' AS src,
        1 AS priority
    FROM bronze.yf_prices
    -- 2026-09-21 (kanban t_0013f4cc): reject no-bar rows at the merge gate.
    -- Pre-2026-07-10 bronze ingest wrote all-NULL weekend/holiday rows; a
    -- NULL close poisoned every rolling-window consumer (SMA200 NaN for 200
    -- days). Filter per-branch so a NULL from a high-priority source falls
    -- back to a lower-priority source with a real close.
    WHERE close IS NOT NULL

    UNION ALL

    -- yfinance commodity futures (priority 1, same source)
    SELECT
        ticker,
        NULL::varchar AS asset_class,
        NULL::varchar AS market,
        date,
        open::numeric(20,8),
        high::numeric(20,8),
        low::numeric(20,8),
        close::numeric(20,8),
        volume::numeric,
        close::numeric(20,8) AS adjusted_close,
        'yfinance' AS src,
        1 AS priority
    FROM bronze.yf_commodity_futures
    WHERE close IS NOT NULL

    UNION ALL

    -- FMP (priority 2)
    SELECT ticker, NULL, NULL, date,
        open::numeric(20,8), high::numeric(20,8),
        low::numeric(20,8), close::numeric(20,8),
        volume::numeric, adjusted_close::numeric(20,8),
        'fmp', 2
    FROM bronze.fmp_prices
    WHERE close IS NOT NULL

    UNION ALL

    -- Manual (priority 3)
    SELECT ticker, NULL, NULL, date,
        open::numeric(20,8), high::numeric(20,8),
        low::numeric(20,8), close::numeric(20,8),
        volume::numeric, adjusted_close::numeric(20,8),
        'manual', 3
    FROM bronze.manual_prices
    WHERE close IS NOT NULL
),
best AS (
    SELECT DISTINCT ON (ticker, date) *
    FROM ranked
    ORDER BY ticker, date, priority
)
SELECT
    b.ticker,
    ar.asset_class,
    ar.market,
    b.date,
    b.open, b.high, b.low, b.close, b.volume, b.adjusted_close,
    -- 1-day return
    ROUND(
        (b.close - LAG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.date))
        / NULLIF(LAG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.date), 0),
        6
    ) AS returns_1d,
    -- log return
    ROUND(
        LN(NULLIF(b.close, 0) / NULLIF(LAG(b.close) OVER (PARTITION BY b.ticker ORDER BY b.date), 0)),
        6
    ) AS returns_log,
    b.src AS source,
    b.src AS primary_source,
    jsonb_build_array(b.src) AS all_sources,
    NOW() AS updated_at
FROM best b
LEFT JOIN silver.asset_registry ar ON ar.ticker = b.ticker
ON CONFLICT (ticker, date) DO UPDATE SET
    open            = EXCLUDED.open,
    high            = EXCLUDED.high,
    low             = EXCLUDED.low,
    close           = EXCLUDED.close,
    volume          = EXCLUDED.volume,
    adjusted_close  = EXCLUDED.adjusted_close,
    returns_1d      = EXCLUDED.returns_1d,
    returns_log     = EXCLUDED.returns_log,
    source          = EXCLUDED.source,
    primary_source  = EXCLUDED.primary_source,
    all_sources     = EXCLUDED.all_sources,
    asset_class     = EXCLUDED.asset_class,
    market          = EXCLUDED.market,
    updated_at      = NOW();
"""

def run():
    snapshot_id = _snapshot_id()
    if not snapshot_id:
        print("❌ REFUSED: silver/clean_unified_prices.py is a full-history merge.")
        print("   Provide --snapshot-id <id> or set SILVER_MERGE_SNAPSHOT_ID /")
        print("   ETL_RUN_SNAPSHOT_ID. The 2026-10-15 restate ran without one;")
        print("   out-of-band restates must snapshot first and pass that id.")
        sys.exit(2)

    conn = get_connection()
    cur = conn.cursor()
    _ensure_snapshot_log(cur)
    cur.execute("SELECT count(*), max(date) FROM silver.unified_prices")
    pre_rows, pre_max_date = cur.fetchone()
    print(f"snapshot_id={snapshot_id} pre_rows={pre_rows} pre_max_date={pre_max_date}")
    # Check if required tables exist
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'bronze' AND table_name = 'fmp_prices'
        );
    """)
    has_fmp = cur.fetchone()[0]
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables 
            WHERE table_schema = 'bronze' AND table_name = 'manual_prices'
        );
    """)
    has_manual = cur.fetchone()[0]
    
    if not has_fmp and not has_manual:
        print("⚠️  No fmp_prices or manual_prices tables — skipping unified prices merge (using yfinance only)")
        # Run simplified version with yfinance + commodity futures
        simple_sql = """
        INSERT INTO silver.unified_prices
            (ticker, asset_class, market, date, open, high, low, close, volume,
             adjusted_close, returns_1d, returns_log, source, primary_source, all_sources, updated_at)
        WITH all_yf AS (
            -- 2026-08-30 (kanban t_3ad38fa3): HO=F/PA=F/RB=F landed in BOTH
            -- bronze.yf_prices and bronze.yf_commodity_futures on 2026-08-24;
            -- the bare UNION ALL then proposed duplicate (ticker,date) rows and
            -- every daily run died on CardinalityViolation (silver frozen at
            -- 2026-08-21 for all non-HK markets). Dedup like the full path's
            -- `best` CTE: yf_prices wins over commodity_futures.
            SELECT DISTINCT ON (ticker, date)
                ticker, date, open, high, low, close, volume, adjusted_close
            FROM (
                SELECT ticker, date, open, high, low, close, volume, adjusted_close, 1 AS prio
                FROM bronze.yf_prices
                WHERE close IS NOT NULL
                UNION ALL
                SELECT ticker, date, open, high, low, close, volume, close AS adjusted_close, 2 AS prio
                FROM bronze.yf_commodity_futures
                WHERE close IS NOT NULL
            ) u
            ORDER BY ticker, date, prio
        )
        SELECT
            yf.ticker,
            ar.asset_class,
            ar.market,
            yf.date,
            yf.open::numeric(20,8),
            yf.high::numeric(20,8),
            yf.low::numeric(20,8),
            yf.close::numeric(20,8),
            yf.volume::numeric,
            yf.adjusted_close::numeric(20,8),
            ROUND(
                (yf.close - LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date))
                / NULLIF(LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date), 0),
                6
            ) AS returns_1d,
            ROUND(
                LN(NULLIF(GREATEST(yf.close, 0.0001), 0) / NULLIF(GREATEST(LAG(yf.close) OVER (PARTITION BY yf.ticker ORDER BY yf.date), 0.0001), 0)),
                6
            ) AS returns_log,
            'yfinance' AS source,
            'yfinance' AS primary_source,
            jsonb_build_array('yfinance') AS all_sources,
            NOW() AS updated_at
        FROM all_yf yf
        LEFT JOIN silver.asset_registry ar ON ar.ticker = yf.ticker
        ON CONFLICT (ticker, date) DO UPDATE SET
            open            = EXCLUDED.open,
            high            = EXCLUDED.high,
            low             = EXCLUDED.low,
            close           = EXCLUDED.close,
            volume          = EXCLUDED.volume,
            adjusted_close  = EXCLUDED.adjusted_close,
            returns_1d      = EXCLUDED.returns_1d,
            returns_log     = EXCLUDED.returns_log,
            source          = EXCLUDED.source,
            primary_source  = EXCLUDED.primary_source,
            all_sources     = EXCLUDED.all_sources,
            asset_class     = EXCLUDED.asset_class,
            market          = EXCLUDED.market,
            updated_at      = NOW();
        """
        cur.execute(simple_sql)
    else:
        cur.execute(UPSERT_SQL)
    print(f"✅ silver.unified_prices — {cur.rowcount} rows upserted")

    # 2026-07-29 (kanban t_034b61f0): post-merge sanity gate, validated INSIDE
    # the transaction so a corrupt bronze source rolls back instead of landing
    # in silver. adjusted_close/close must sit in [0.02, 50] — a volume/
    # adjusted_close column swap upstream (see oneoff backfill_universe_yf
    # incident) lands at ~1e5x and would otherwise propagate silently to every
    # consumer of silver.unified_prices.
    cur.execute("""
        SELECT ticker, COUNT(*) AS n,
               MIN(date) AS first_date, MAX(date) AS last_date
        FROM silver.unified_prices
        WHERE close > 0 AND adjusted_close IS NOT NULL
          AND (adjusted_close / close > 50 OR adjusted_close / close < 0.02)
        GROUP BY ticker
        ORDER BY n DESC
        LIMIT 20
    """)
    violations = cur.fetchall()
    if violations:
        conn.rollback()
        print("❌ SANITY GATE FAILED — silver.unified_prices merge rolled back.")
        print(f"   {len(violations)} tickers (top 20 shown) with "
              f"adjusted_close/close outside [0.02, 50]:")
        for t, n, d0, d1 in violations:
            print(f"   {t}: {n} rows  {d0}..{d1}")
        print("   Fix the bronze source and re-run. See kanban t_034b61f0.")
        conn.close()
        sys.exit(1)

    cur.execute("SELECT count(*), max(date) FROM silver.unified_prices")
    post_rows, post_max_date = cur.fetchone()
    cur.execute("""
        INSERT INTO gold.etl_snapshot_log
            (snapshot_id, scope, script, pre_rows, pre_max_date, post_rows, post_max_date, note)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (snapshot_id) DO UPDATE SET
            post_rows = EXCLUDED.post_rows,
            post_max_date = EXCLUDED.post_max_date,
            note = EXCLUDED.note
    """, (snapshot_id, 'silver.unified_prices full-history merge',
          'silver/clean_unified_prices.py', pre_rows, pre_max_date,
          post_rows, post_max_date,
          'scheduled run id from runner/wrapper; manual restates must pass a backup snapshot id'))
    print(f"snapshot logged: {snapshot_id} post_rows={post_rows} post_max_date={post_max_date}")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
