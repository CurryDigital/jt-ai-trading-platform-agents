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
}

CHUNK_SIZE = 100
SLEEP_BETWEEN_CHUNKS = 0.5

# ── Helpers ───────────────────────────────────────────────────────────────────

def get_active_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker FROM gold.asset_registry
        WHERE is_active = TRUE
          AND asset_class IN ('STOCK', 'ETF', 'INDEX')
        ORDER BY market = 'US' DESC, ticker
    """)
    return [r[0] for r in cur.fetchall()]

def get_commodity_tickers(conn) -> list:
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ticker FROM bronze.yf_commodity_futures
        UNION
        SELECT ticker FROM gold.asset_registry
        WHERE asset_class = 'COMMODITY'
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
    global _n_row_errors, _n_rows_attempted
    from psycopg2.extras import execute_values

    rows = []
    for _, row in df.iterrows():
        # 2026-07-10 (P1-7): don't insert no-bar rows. Yahoo returns all-NaN
        # rows for market holidays (e.g. 2026-06-19 Juneteenth) when a batch
        # includes any ticker that DID trade that day. A NULL-close row is
        # useless to every consumer and one such row blocked gold.daily_ohlcv
        # for SPY for 15 days — a missing row is the honest representation of
        # "no bar happened".
        if not pd.notna(row['Close']):
            continue
        rows.append((
            ticker,
            row['Date'].date() if hasattr(row['Date'], 'date') else row['Date'],
            float(row['Open'])   if pd.notna(row['Open'])   else None,
            float(row['High'])   if pd.notna(row['High'])   else None,
            float(row['Low'])    if pd.notna(row['Low'])    else None,
            float(row['Close']),
            int(row['Volume'])   if pd.notna(row['Volume']) else None,
            float(row['Close']),
        ))

    if not rows:
        return 0
    _n_rows_attempted += len(rows)

    try:
        cur.execute("SAVEPOINT upsert_batch")
        execute_values(cur, _UPSERT_PRICES_SQL, rows,
                       template=_UPSERT_PRICES_TEMPLATE, page_size=500)
        cur.execute("RELEASE SAVEPOINT upsert_batch")
        return len(rows)
    except Exception as batch_err:
        cur.execute("ROLLBACK TO SAVEPOINT upsert_batch")
        print(f"    Batch upsert failed for {ticker} ({batch_err}) — retrying row-by-row")

    inserted = 0
    single_sql = _UPSERT_PRICES_SQL.replace("VALUES %s", f"VALUES {_UPSERT_PRICES_TEMPLATE}")
    for r in rows:
        try:
            cur.execute("SAVEPOINT upsert_row")
            cur.execute(single_sql, r)
            cur.execute("RELEASE SAVEPOINT upsert_row")
            inserted += 1
        except Exception as e:
            cur.execute("ROLLBACK TO SAVEPOINT upsert_row")
            _n_row_errors += 1
            print(f"    Row error {ticker} {r[1]}: {e}")
    return inserted

# ── Equity / ETF Prices (chunked) ─────────────────────────────────────────────

def ingest_yf_prices(tickers: list = None, days_back: int = 10, max_tickers: int = None):
    conn = get_connection()
    if tickers is None:
        tickers = get_active_tickers(conn)
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

def ingest_commodity_futures(days_back: int = 7, max_tickers: int = 10):
    conn = get_connection()
    tickers = get_commodity_tickers(conn)[:max_tickers]
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
    behind individual `Row error {ticker}: ...` prints."""
    if _n_rows_attempted == 0:
        return
    rate = _n_row_errors / _n_rows_attempted
    print(f"\n  Row stats: {_n_row_errors} errors / {_n_rows_attempted} attempted "
          f"({rate:.1%})  threshold={ROW_ERROR_RATE_THRESHOLD:.0%}")
    if rate > ROW_ERROR_RATE_THRESHOLD:
        print(f"  ⚠️ row error rate exceeds threshold — exiting non-zero")
        _mark_freshness(error=f"row_error_rate={rate:.2%} ({_n_row_errors}/{_n_rows_attempted})")
        sys.exit(1)


if __name__ == "__main__":
    # freshness_guard (P1-6) marks gold.source_freshness on success and
    # records + re-raises on failure. The row-error-rate gate runs after:
    # it may overwrite the success mark with an error and exit non-zero.
    from freshness import freshness_guard
    with freshness_guard(source='yfinance'):
        ingest_yf_prices()
        ingest_commodity_futures()
    _check_row_error_rate()
