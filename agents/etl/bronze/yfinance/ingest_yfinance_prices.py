# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Bronze Ingestion: Yahoo Finance — Prices Only (Daily Regime Pipeline)
=====================================================================
Fetches OHLCV + adjusted close for core tickers.
Chunked yf.download() for speed: 100 tickers per batch.
Target runtime: < 60 seconds for 766 tickers

Tables:
  bronze.yf_prices — daily OHLCV for equities/ETFs/indices
  bronze.yf_commodity_futures — commodity futures OHLCV
"""
import sys, os, time
try:
    import pandas as pd
except ImportError:
    pass
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta

try:
    import yfinance as yf
except ImportError:
    print("⚠️  yfinance not installed — run: pip install yfinance")
    sys.exit(1)

# ── Default ticker list for regime pipeline ───────────────────────────────────
DEFAULT_TICKERS = [
    'SPY', 'QQQ', 'GLD', 'USO', 'BTC-USD', 'ETH-USD',
    'AAPL', 'MSFT', 'AMZN', 'GOOGL', 'META', 'TSLA', 'NVDA',
    'JPM', 'JNJ', 'V', 'WMT', 'PG', 'UNH', 'HD', 'MA', 'BAC',
    'JPY=X', 'UNG', 'EURUSD=X', 'TLT', 'FCG', 'IWM', 'XLE',
]

COMMODITY_META = {
    'GC=F': ('Gold Futures',       'metals',    'COMEX'),
    'SI=F': ('Silver Futures',     'metals',    'COMEX'),
    'CL=F': ('Crude Oil Futures',  'energy',    'NYMEX'),
    'NG=F': ('Natural Gas Futures','energy',    'NYMEX'),
    'HG=F': ('Copper Futures',     'metals',    'COMEX'),
    'ZW=F': ('Wheat Futures',      'grains',    'CBOT'),
    'ZS=F': ('Soybean Futures',    'grains',    'CBOT'),
    'ZC=F': ('Corn Futures',       'grains',    'CBOT'),
    'KC=F': ('Coffee Futures',     'softs',     'ICE'),
    'SB=F': ('Sugar Futures',      'softs',     'ICE'),
    # 2026-08-24 (kanban t_49eb69fa): registry hygiene — RB=F/HO=F/PA=F (+BZ=F,
    # inactive) were misclassified asset_class='STOCK'/market='US', so pipeline A
    # fetched them via the equity path and they polluted US STOCK/ETF layer
    # counts. Reclassified to COMMODITY/GLOBAL; they now flow through
    # ingest_commodity_futures() and need real META (was falling back to
    # 'unknown'). PL=F was already COMMODITY in the registry but missing here.
    'RB=F': ('RBOB Gasoline Futures','energy',  'NYMEX'),
    'HO=F': ('Heating Oil Futures', 'energy',   'NYMEX'),
    'PA=F': ('Palladium Futures',   'metals',   'NYMEX'),
    'BZ=F': ('Brent Crude Futures', 'energy',   'NYMEX'),
    'PL=F': ('Platinum Futures',    'metals',   'NYMEX'),
}

CHUNK_SIZE = 100
SLEEP_BETWEEN_CHUNKS = 0.5

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_active_tickers(conn, markets: list = None) -> list:
    cur = conn.cursor()
    # 2026-08-06 (kanban t_464bcdb1): include FX/CURRENCY. All 15 '=X' pairs
    # are registered with asset_class='FX' (JPY=X as 'CURRENCY') and were
    # silently excluded from every daily ingest since registration — they
    # froze at 2026-02-27 while the pipeline stayed GREEN (same failure mode
    # as the 'HK Stock' labels in t_b735bbbd). yfinance serves '=X' FX pairs
    # from the same download endpoint, so no fetch-path change is needed.
    #
    # 2026-08-19 (kanban t_817e5f40): optional `markets` filter for the
    # post-close US top-up run (22:30 UTC). Yahoo withholds the most recent
    # US equity daily bar in the early-morning ET window (confirmed absent
    # at 04:30 ET for 625/627 US stocks while futures/FX landed fine, then
    # present same-evening by 21:30 ET), so the 08:30 UTC run systematically
    # misses D-1 US bars. The evening top-up re-fetches US tickers only.
    # 2026-09-26 (kanban t_68887aff): UNION open manual-book symbols. The
    # Manual book (gold.manual_positions) accepts ANY discretionary ticker,
    # but the ingest universe was registry-only, so an ad-hoc manual position
    # (SPCX) never got a single bar and showed unscored P&L. Fallback: every
    # manual_positions symbol (open or closed — closed rows are few and the
    # bars are cheap) joins the universe even before/without a registry row.
    sql = """
        SELECT ticker FROM gold.asset_registry
        WHERE is_active = TRUE
          AND asset_class IN ('STOCK', 'ETF', 'INDEX', 'FX', 'CURRENCY', 'CRYPTO')
    """
    manual_sql = """
        SELECT DISTINCT symbol AS ticker, market FROM gold.manual_positions
        WHERE symbol IS NOT NULL
    """
    params = []
    if markets:
        sql += " AND market = ANY(%s)"
        params.append(markets)
        manual_sql += " AND market = ANY(%s)"
        params.append(markets)
    sql = f"SELECT u.ticker FROM ({sql.replace('SELECT ticker', 'SELECT ticker, market')} UNION {manual_sql}) u"
    # US-first order preserved: the 08:30 UTC run has a 120s manifest budget
    # and must land US bars before HK/SG/CN/FX (t_6cf1b88b).
    sql += " ORDER BY (u.market = 'US') DESC NULLS LAST, u.ticker"
    cur.execute(sql, params)
    return [r[0] for r in cur.fetchall()]

def get_commodity_tickers(conn) -> list:
    cur = conn.cursor()
    # 2026-08-18 (kanban t_d4a629a3): deterministic ORDER BY. The UNION has no
    # inherent order and ingest_commodity_futures() truncated to [:10] — once
    # bronze held 11 distinct '=F' tickers, ZW=F fell outside an arbitrary
    # first-10 and silently froze at 2026-06-15 while cron stayed GREEN.
    cur.execute("""
        SELECT DISTINCT ticker FROM bronze.yf_commodity_futures
        UNION
        SELECT ticker FROM gold.asset_registry
        WHERE asset_class = 'COMMODITY'
          AND is_active = TRUE
        ORDER BY 1
    """)
    return [r[0] for r in cur.fetchall()] or list(COMMODITY_META.keys())

# Module-level row-error tracking (ported from the deleted ingest_yfinance.py
# 2026-07-10 when the two double-ingesting scripts were consolidated into this
# one). If the row error rate crosses 5% of attempts, main() exits non-zero so
# cron + gold.source_freshness see the truth instead of a green checkmark over
# a mostly-failed ingest.
_n_row_errors = 0
_n_rows_attempted = 0
ROW_ERROR_RATE_THRESHOLD = 0.05

# 2026-07-29 (kanban t_034b61f0): sanity gate on the load path. A one-off
# backfill with a positional volume/adjusted_close swap poisoned 43,584 rows
# in bronze.yf_prices and silver.unified_prices; nothing downstream flagged it
# because every column was individually plausible. adjusted_close/close for a
# sane equity/ETF row is always within [0.02, 50] (even a 50:1 split or heavy
# dividend history stays inside); a swapped volume column lands at ~1e5x.
# Rows failing the ratio are refused and counted as row errors, so a mass
# corruption trips the 5% gate and exits non-zero instead of loading green.
ADJ_CLOSE_RATIO_MIN = 0.02
ADJ_CLOSE_RATIO_MAX = 50.0


def _sane_adj_close(close_val, adj_val) -> bool:
    if close_val is None or adj_val is None or close_val <= 0:
        return True  # NULLs handled by existing no-bar / COALESCE logic
    ratio = adj_val / close_val
    return ADJ_CLOSE_RATIO_MIN <= ratio <= ADJ_CLOSE_RATIO_MAX


# 2026-08-24 (kanban t_d97f3b82): Yahoo synthetic placeholder-bar guard.
# Around corporate actions (AVB 2.793:1 merger exchange 2026-08-17; EQR
# 2026-08-18; EA 2026-08-05..10, self-healed) Yahoo's v8 chart API serves
# synthetic placeholder bars: volume=0, open=high=low=close pinned to the
# prior close. They used to flow bronze -> silver -> gold as real sessions.
# A US STOCK/ETF row is SUSPECT when volume==0 AND OHLC perfectly flat AND
# the flat close equals the prior close (stored in bronze, or the previous
# row of the same fetched frame — the fetched-frame check still fires after
# Yahoo retroactively split-adjusts history, which breaks the stored-close
# comparison). Suspect rows are NOT written as normal bars: they are logged,
# counted separately from row errors, and quarantined in
# bronze.yf_suspect_bars (surfaced by gold.v_us_equity_bar_quality).
_n_suspect_rows = 0
_suspect_keys = set()  # (ticker, date) withheld this run

# Corporate-action rewrite guard: yf.download(auto_adjust=True) retroactively
# rewrites historical closes when Yahoo records a new split. For a date that
# already exists in bronze, a fetched close differing by more than
# CORP_ACTION_REWRITE_TOL from the stored close is a split rewrite, not a
# price correction — block it and require an explicit corporate-action
# migration before history may be restated.
_n_corp_action_rows = 0
_corp_action_tickers = set()
CORP_ACTION_REWRITE_TOL = 0.01

_US_EQUITY_TICKERS = None  # lazy: active US STOCK/ETF universe for the guard


def _us_equity_tickers(conn):
    global _US_EQUITY_TICKERS
    if _US_EQUITY_TICKERS is None:
        cur = conn.cursor()
        cur.execute("""
            SELECT ticker FROM gold.asset_registry
            WHERE market = 'US' AND asset_class IN ('STOCK', 'ETF')
              AND is_active = TRUE
        """)
        _US_EQUITY_TICKERS = {r[0] for r in cur.fetchall()}
    return _US_EQUITY_TICKERS


def _quarantine_suspect(cur, ticker, row_date, o, h, l, close_val, volume, adj_val):
    """Record a withheld suspect bar. Soft-fails: quarantine must never
    break the ingest itself."""
    try:
        cur.execute("SAVEPOINT quarantine_row")
        cur.execute("""
            INSERT INTO bronze.yf_suspect_bars
                (ticker, date, open, high, low, close, volume, adjusted_close,
                 reason, detected_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                    'zero_volume_flat_placeholder', NOW())
            ON CONFLICT (ticker, date) DO UPDATE SET
                detected_at = NOW(),
                open = EXCLUDED.open, high = EXCLUDED.high,
                low = EXCLUDED.low, close = EXCLUDED.close,
                volume = EXCLUDED.volume,
                adjusted_close = EXCLUDED.adjusted_close
        """, (ticker, row_date, o, h, l, close_val, volume, adj_val))
        cur.execute("RELEASE SAVEPOINT quarantine_row")
    except Exception as e:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT quarantine_row")
        except Exception:
            pass
        print(f"    (quarantine write skipped for {ticker} {row_date}: {e})")


def _resolve_suspects(cur, ticker, written_dates):
    """Real bars landed for (ticker, date) — mark any quarantined suspects
    resolved (the EA 2026-08-05..10 self-heal pattern). Soft-fails."""
    if not written_dates:
        return
    try:
        cur.execute("SAVEPOINT resolve_suspects")
        cur.execute("""
            UPDATE bronze.yf_suspect_bars SET resolved_at = NOW()
            WHERE ticker = %s AND date = ANY(%s) AND resolved_at IS NULL
        """, (ticker, list(written_dates)))
        if cur.rowcount:
            print(f"    {ticker}: {cur.rowcount} quarantined suspect(s) resolved by real bars")
        cur.execute("RELEASE SAVEPOINT resolve_suspects")
    except Exception as e:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT resolve_suspects")
        except Exception:
            pass
        print(f"    (suspect resolve skipped for {ticker}: {e})")


_UPSERT_PRICES_SQL = """
    INSERT INTO bronze.yf_prices
        (ticker, date, open, high, low, close, volume,
         adjusted_close, ingested_at)
    VALUES %s
    ON CONFLICT (ticker, date) DO UPDATE SET
        open = COALESCE(EXCLUDED.open, bronze.yf_prices.open),
        high = COALESCE(EXCLUDED.high, bronze.yf_prices.high),
        low = COALESCE(EXCLUDED.low, bronze.yf_prices.low),
        close = COALESCE(EXCLUDED.close, bronze.yf_prices.close),
        volume = COALESCE(EXCLUDED.volume, bronze.yf_prices.volume),
        adjusted_close = COALESCE(EXCLUDED.adjusted_close, bronze.yf_prices.adjusted_close)
"""
_UPSERT_PRICES_TEMPLATE = "(%s, %s, %s, %s, %s, %s, %s, %s, NOW())"


def _upsert_prices(cur, ticker, df):
    """Upsert a single ticker's price DataFrame. Returns inserted count.

    2026-07-03: ON CONFLICT COALESCEs every column instead of only refreshing
    close/volume/adjusted_close. Yahoo often returns a same-day row with Close
    populated but Open/High/Low still NaN (bar not finalized); the old clause
    froze open/high/low at NULL forever because it never wrote them again.

    2026-07-10 (P1-4): batched via execute_values — one statement per ticker
    instead of one DB round trip per (ticker, date) row (~10k round trips per
    daily run). On a batch failure, falls back to row-by-row with SAVEPOINTs
    to isolate the bad row(s). The savepoints also fix a latent bug in the
    old loop: the first row error aborted the whole transaction, so every
    subsequent "row error" was really InFailedSqlTransaction noise and the
    remaining rows of the batch were silently lost.
    """
    global _n_row_errors, _n_rows_attempted, _n_suspect_rows, _n_corp_action_rows
    from psycopg2.extras import execute_values

    # 2026-08-24 (kanban t_d97f3b82): load this ticker's stored closes once —
    # needed by the placeholder guard (prior stored close) and the corporate-
    # action rewrite guard (fetched vs stored on already-ingested dates).
    stored_closes = {}
    try:
        cur.execute("SAVEPOINT load_stored")
        cur.execute("""
            SELECT date, close FROM bronze.yf_prices
            WHERE ticker = %s AND date >= %s
        """, (ticker, (date.today() - timedelta(days=90))))
        stored_closes = {r[0]: float(r[1]) for r in cur.fetchall() if r[1] is not None}
        cur.execute("RELEASE SAVEPOINT load_stored")
    except Exception as e:
        try:
            cur.execute("ROLLBACK TO SAVEPOINT load_stored")
        except Exception:
            pass
        print(f"    (stored-close preload skipped for {ticker}: {e})")

    is_us_equity = ticker in _us_equity_tickers(cur.connection)

    rows = []
    prev_fetched_close = None  # previous row of THIS frame (df is date-ordered)
    for _, row in df.iterrows():
        # 2026-07-10 (P1-7): don't insert no-bar rows. Yahoo returns all-NaN
        # rows for market holidays (e.g. 2026-06-19 Juneteenth) when a batch
        # includes any ticker that DID trade that day. A NULL-close row is
        # useless to every consumer and one such row blocked gold.daily_ohlcv
        # for SPY for 15 days — a missing row is the honest representation of
        # "no bar happened".
        if not pd.notna(row['Close']):
            continue
        close_val = float(row['Close'])
        adj_val = close_val  # auto_adjust=True download: adjusted_close == close
        row_date = row['Date'].date() if hasattr(row['Date'], 'date') else row['Date']
        vol_val = int(row['Volume']) if pd.notna(row['Volume']) else None
        o_val = float(row['Open'])  if pd.notna(row['Open'])  else None
        h_val = float(row['High'])  if pd.notna(row['High'])  else None
        l_val = float(row['Low'])   if pd.notna(row['Low'])   else None

        if not _sane_adj_close(close_val, adj_val):
            _n_rows_attempted += 1
            _n_row_errors += 1
            print(f"    SANITY REJECT {ticker} {row['Date']}: "
                  f"adjusted_close/close={adj_val/close_val:.4g} outside "
                  f"[{ADJ_CLOSE_RATIO_MIN}, {ADJ_CLOSE_RATIO_MAX}]")
            prev_fetched_close = close_val
            continue

        # Placeholder-bar guard (US STOCK/ETF only): volume=0 + perfectly
        # flat OHLC + flat close == prior close -> Yahoo synthetic bar around
        # a corporate action. Withhold, quarantine, count separately.
        if (is_us_equity and vol_val == 0
                and o_val is not None and h_val is not None and l_val is not None
                and o_val == h_val == l_val == close_val):
            prior_stored = None
            earlier = [d for d in stored_closes if d < row_date]
            if earlier:
                prior_stored = stored_closes[max(earlier)]
            matches_stored = (prior_stored is not None
                              and abs(close_val - prior_stored) <= 1e-6)
            matches_fetched = (prev_fetched_close is not None
                               and abs(close_val - prev_fetched_close) <= 1e-6)
            if matches_stored or matches_fetched:
                _n_suspect_rows += 1
                _suspect_keys.add((ticker, row_date))
                print(f"    SUSPECT PLACEHOLDER {ticker} {row_date}: "
                      f"volume=0 flat OHLC close={close_val} "
                      f"(prior {'stored' if matches_stored else 'fetched'} close match) — withheld")
                _quarantine_suspect(cur, ticker, row_date, o_val, h_val, l_val,
                                    close_val, vol_val, adj_val)
                prev_fetched_close = close_val
                continue

        # Corporate-action rewrite guard: never let auto_adjust=True silently
        # restate an already-ingested close (e.g. AVB 2.793:1 on 2026-08-17
        # turning 184.06 into ~65.90). Requires an explicit migration.
        stored = stored_closes.get(row_date)
        if stored is not None and stored > 0:
            rel = abs(close_val / stored - 1.0)
            if rel > CORP_ACTION_REWRITE_TOL:
                _n_corp_action_rows += 1
                _corp_action_tickers.add(ticker)
                print(f"    CORP ACTION REWRITE BLOCKED {ticker} {row_date}: "
                      f"fetched close {close_val} vs stored {stored} "
                      f"({rel:.1%} drift) — split event suspected; run an explicit "
                      f"corporate-action migration to restate history")
                prev_fetched_close = close_val
                continue

        rows.append((
            ticker,
            row_date,
            o_val,
            h_val,
            l_val,
            close_val,
            vol_val,
            adj_val,
        ))
        prev_fetched_close = close_val

    if not rows:
        return 0
    _n_rows_attempted += len(rows)

    try:
        cur.execute("SAVEPOINT upsert_batch")
        execute_values(cur, _UPSERT_PRICES_SQL, rows,
                       template=_UPSERT_PRICES_TEMPLATE, page_size=500)
        cur.execute("RELEASE SAVEPOINT upsert_batch")
        _resolve_suspects(cur, ticker, [r[1] for r in rows])
        return len(rows)
    except Exception as batch_err:
        cur.execute("ROLLBACK TO SAVEPOINT upsert_batch")
        print(f"    Batch upsert failed for {ticker} ({batch_err}) — retrying row-by-row")

    inserted = 0
    written_dates = []
    single_sql = _UPSERT_PRICES_SQL.replace("VALUES %s", f"VALUES {_UPSERT_PRICES_TEMPLATE}")
    for r in rows:
        try:
            cur.execute("SAVEPOINT upsert_row")
            cur.execute(single_sql, r)
            cur.execute("RELEASE SAVEPOINT upsert_row")
            inserted += 1
            written_dates.append(r[1])
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT upsert_row")
            _n_row_errors += 1
            print(f"    Row error {ticker} {r[1]}: {e}")
    _resolve_suspects(cur, ticker, written_dates)
    return inserted

# ── Equity / ETF Prices (chunked) ─────────────────────────────────────────────

def ingest_yf_prices(tickers: list = None, days_back: int = 10, max_tickers: int = None,
                     markets: list = None):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn, markets=markets)
        if not tickers:
            tickers = DEFAULT_TICKERS
        if max_tickers:
            tickers = tickers[:max_tickers]
    elif max_tickers:
        tickers = tickers[:max_tickers]

    if not tickers:
        print("⚠️  No tickers to ingest")
        conn.close()
        return

    start = (date.today() - timedelta(days=days_back)).isoformat()
    print(f"  Fetching {len(tickers)} tickers from {start} in chunks of {CHUNK_SIZE}…")

    cur = conn.cursor()
    inserted = 0
    failures = []

    for i in range(0, len(tickers), CHUNK_SIZE):
        chunk = tickers[i:i + CHUNK_SIZE]
        try:
            data = yf.download(chunk, start=start, auto_adjust=True, progress=False)
            if len(chunk) == 1:
                ticker = chunk[0]
                # 2026-09-29: current yfinance returns MultiIndex (Price, Ticker)
                # columns even for a 1-ticker download — the old bare
                # reset_index() left row['Close'] as a Series and _upsert_prices
                # died on "truth value of a Series is ambiguous" (VXUS manual-
                # book backfill). Use the same xs() extraction as the multi-
                # ticker path when columns are MultiIndex.
                if isinstance(data.columns, pd.MultiIndex):
                    df = data.xs(ticker, axis=1, level=1).reset_index()
                else:
                    df = data.reset_index()
                inserted += _upsert_prices(cur, ticker, df)
            else:
                for ticker in chunk:
                    try:
                        df = data.xs(ticker, axis=1, level=1).reset_index()
                        inserted += _upsert_prices(cur, ticker, df)
                    except Exception as e:
                        failures.append((ticker, str(e)))
                        print(f"  Ticker error {ticker}: {e}")
        except Exception as e:
            failures.append((chunk[0] if chunk else 'unknown', str(e)))
            print(f"  Chunk error starting {chunk[0]}: {e}")

        if i + CHUNK_SIZE < len(tickers):
            time.sleep(SLEEP_BETWEEN_CHUNKS)

    conn.commit()
    conn.close()

    if failures:
        print(f"  ⚠️  {len(failures)} tickers failed (logged above)")
    limit_note = f" (limited to {max_tickers} tickers)" if max_tickers else ""
    print(f"✅ bronze.yf_prices — {inserted} rows upserted{limit_note}")


# ── Commodity Futures ─────────────────────────────────────────────────────────

def ingest_commodity_futures(days_back: int = 7, max_tickers: int = None):
    conn = get_connection()
    # 2026-08-18 (kanban t_d4a629a3): no default truncation — an arbitrary
    # [:10] over an 11-ticker universe silently starved ZW=F for 2 months.
    tickers = get_commodity_tickers(conn)
    if max_tickers:
        tickers = tickers[:max_tickers]
    start   = (date.today() - timedelta(days=days_back)).isoformat()

    cur = conn.cursor()
    inserted = 0

    for ticker in tickers:
        try:
            data = yf.download(ticker, start=start, auto_adjust=True, progress=False)
            # Flatten multi-level columns (e.g. ('Close','CL=F')) to single level
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            meta = COMMODITY_META.get(ticker, (ticker, 'unknown', 'unknown'))

            for ts, row in data.iterrows():
                if not pd.notna(row['Close']):  # no-bar (holiday) row — skip, see _upsert_prices
                    continue
                try:
                    cur.execute("""
                        INSERT INTO bronze.yf_commodity_futures
                            (ticker, name, category, exchange, date,
                             open, high, low, close, volume, adjusted_close, ingested_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                        ON CONFLICT (ticker, date) DO UPDATE SET
                            open = COALESCE(EXCLUDED.open, bronze.yf_commodity_futures.open),
                            high = COALESCE(EXCLUDED.high, bronze.yf_commodity_futures.high),
                            low = COALESCE(EXCLUDED.low, bronze.yf_commodity_futures.low),
                            close = COALESCE(EXCLUDED.close, bronze.yf_commodity_futures.close),
                            volume = COALESCE(EXCLUDED.volume, bronze.yf_commodity_futures.volume),
                            adjusted_close = COALESCE(EXCLUDED.adjusted_close, bronze.yf_commodity_futures.adjusted_close)
                    """, (
                        ticker, meta[0], meta[1], meta[2],
                        ts.date(),
                        float(row['Open'])  if pd.notna(row['Open'])  else None,
                        float(row['High'])  if pd.notna(row['High'])  else None,
                        float(row['Low'])   if pd.notna(row['Low'])   else None,
                        float(row['Close']) if pd.notna(row['Close']) else None,
                        int(row['Volume'])  if pd.notna(row['Volume']) else None,
                        float(row['Close']) if pd.notna(row['Close']) else None,
                    ))
                    inserted += 1
                except Exception as e:
                    print(f"    Row error {ticker} {ts}: {e}")
        except Exception as e:
            print(f"  Ticker error {ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.yf_commodity_futures — {inserted} rows upserted")


def _mark_freshness(error=None):
    """Update gold.source_freshness for the operator dashboard. Soft-fails."""
    try:
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='yfinance', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


def _check_row_error_rate():
    """Exit non-zero if too many rows failed — masks would otherwise hide
    behind individual `Row error {ticker}: ...` prints.

    2026-08-24 (kanban t_d97f3b82): withheld suspect placeholders and blocked
    corporate-action rewrites are reported on their own lines and do NOT
    count toward the error rate — a run that only withheld suspects still
    exits 0; only a real error-rate breach exits non-zero."""
    suspect_note = ""
    if _n_suspect_rows:
        tickers = sorted({t for t, _ in _suspect_keys})
        suspect_note = (f"\n  Suspect placeholders withheld: {_n_suspect_rows} rows "
                        f"across {len(_suspect_keys)} (ticker,date) — tickers: "
                        f"{','.join(tickers)} (quarantined in bronze.yf_suspect_bars; "
                        f"see gold.v_us_equity_bar_quality)")
    corp_note = ""
    if _n_corp_action_rows:
        corp_note = (f"\n  Corporate-action rewrites blocked: {_n_corp_action_rows} rows — "
                     f"tickers: {','.join(sorted(_corp_action_tickers))} "
                     f"(explicit corporate-action migration required to restate history)")
    if _n_rows_attempted == 0:
        print(f"\n  Row stats: 0 attempted.{suspect_note}{corp_note}")
        return
    rate = _n_row_errors / _n_rows_attempted
    print(f"\n  Row stats: {_n_row_errors} errors / {_n_rows_attempted} attempted "
          f"({rate:.1%})  threshold={ROW_ERROR_RATE_THRESHOLD:.0%}"
          f"{suspect_note}{corp_note}")
    if rate > ROW_ERROR_RATE_THRESHOLD:
        print(f"  ⚠️ row error rate exceeds threshold — exiting non-zero")
        _mark_freshness(error=f"row_error_rate={rate:.2%} ({_n_row_errors}/{_n_rows_attempted})")
        sys.exit(1)


if __name__ == "__main__":
    # freshness_guard (P1-6) marks gold.source_freshness on success and
    # records + re-raises on failure. The row-error-rate gate runs after:
    # it may overwrite the success mark with an error and exit non-zero.
    #
    # 2026-08-19 (kanban t_817e5f40): --markets US restricts the equity
    # universe for the 22:30 UTC post-close top-up and skips the commodity
    # futures pass (futures bars are served fine at the 08:30 UTC run).
    # 2026-09-10 (kanban t_6cf1b88b): the 08:30 UTC run timed out at its 120s
    # manifest budget mid-universe (US-first order) and silently dropped
    # HK/SG/CN/FX/FUT Sep 09 bars. The manifest now chunks the stage per
    # market group; --futures-only supports the separate commodity-futures
    # stage. No flags = legacy full-universe run (manual backfills).
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--markets', default=None,
                    help="Comma-separated market filter (e.g. 'US'). "
                         "When set, commodity futures ingest is skipped.")
    ap.add_argument('--futures-only', action='store_true',
                    help="Ingest commodity futures only; equity universe skipped.")
    args = ap.parse_args()
    markets = [m.strip() for m in args.markets.split(',')] if args.markets else None
    from freshness import freshness_guard
    with freshness_guard(source='yfinance'):
        if args.futures_only:
            ingest_commodity_futures()
        else:
            ingest_yf_prices(markets=markets)
            if not markets:
                ingest_commodity_futures()
    _check_row_error_rate()
