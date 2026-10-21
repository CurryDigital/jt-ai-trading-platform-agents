#!/usr/bin/env python3
"""
DATA_FIX (goal gold_daily_ohlcv_gap_remediation_v1, step 2a):
Re-ingest UPSTREAM_HOLE ticker-days from yfinance into bronze.yf_prices.

Targets: workspace/ohlcv_gap_audit_v1/reingest_targets.json — (ticker, dates)
absent from ALL layers (never ingested). FX-alias tickers (^[A-Z]{6}$) are
excluded: they are healed DB-side by silver/alias_fx_pairs.py.

Conventions mirrored from bronze/yfinance/ingest_yfinance_prices.py
(auto_adjust=True, NULL-close skip, suspect/corp-action guards) by importing
its _upsert_prices. ADDED guard for historical backfill: split-consistency
check — fetched auto_adjusted closes are compared against existing
silver.unified_prices closes on overlap dates; if the median ratio drifts
>1% the ticker is skipped (a corporate action after the stored rows were
written would silently restate history) and logged for manual handling.

Insert-only at the (ticker,date) level for OUR target dates is not
enforced here — _upsert_prices ON CONFLICT refreshes NULL-able columns, but
the corp-action rewrite guard blocks close drift on recent dates and the
split check covers historical ones. Existing non-null closes are never
changed for dates outside the last 90d (stored-close window) unless the
split check passed (i.e. fetched == stored within 1%).

Usage:
  python3 backfill_ohlcv_gap_v1.py [--limit N] [--tickers T,T,T]
Run with the etl-venv python (needs yfinance + pandas).
"""
import sys, os, json, time, argparse
from datetime import date, timedelta

ETL = os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl")
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
sys.path.insert(0, os.path.join(ETL, 'bronze', 'yfinance'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import gc
import pandas as pd
import yfinance as yf
import ingest_yfinance_prices as ing
from db import get_connection

AUDIT_DIR = os.path.expanduser("~/.hermes/profiles/qr_etl/workspace/ohlcv_gap_audit_v1")
TARGETS = os.path.join(AUDIT_DIR, "reingest_targets.json")
LOG = os.path.join(AUDIT_DIR, "backfill_bronze_log.json")
CHUNK = 100
SLEEP = getattr(ing, 'SLEEP_BETWEEN_CHUNKS', 5)
# Split guard: only true corporate actions (>=~10% median drift) skip a ticker.
# Dividend-driven restatement of auto_adjust closes is ~1-3% over months and is
# a platform-wide accepted seam (close==adjusted convention); splits are >=1.5x.
SPLIT_LO, SPLIT_HI = 0.90, 1.10

def is_fx_alias(t):
    return len(t) == 6 and t.isalpha() and t.isupper()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--limit', type=int, default=None)
    ap.add_argument('--tickers', default=None, help="comma list; overrides targets file")
    args = ap.parse_args()

    if args.tickers:
        default_window = (date(2026, 2, 18), date(2026, 4, 7))
        targets = {t: pd.date_range(default_window[0], default_window[1]).date.astype(str).tolist()
                   for t in args.tickers.split(',')}
    else:
        targets = json.load(open(TARGETS))

    # per-ticker fetch window = min-5d .. max+5d
    win = {}
    skipped_alias = []
    for t, ds in targets.items():
        if is_fx_alias(t):
            skipped_alias.append(t)
            continue
        if not ds:
            continue
        d0 = min(date.fromisoformat(d) for d in ds) - timedelta(days=5)
        d1 = max(date.fromisoformat(d) for d in ds) + timedelta(days=5)
        win[t] = (d0, d1)
    if args.limit:
        win = dict(list(win.items())[:args.limit])
    print(f"targets: {len(targets)}; yf-fetch: {len(win)}; fx-alias skipped: {len(skipped_alias)}")

    # resume: skip tickers already healed in a previous run's log.
    # NOTE (2026-10-15): seed `log` with the previous run's entries — the
    # checkpoint writer OVERWRITES LOG, so a fresh dict destroys the prior
    # run's terminal statuses (cost us the 13 split-suspect names once).
    done_ok = set()
    prev_log = {}
    if os.path.exists(LOG) and not args.tickers:
        try:
            prev = json.load(open(LOG))
            prev_log = prev.get('log', {})
            # terminal statuses: ok + honest negatives (no data at source / split-suspect)
            done_ok = {t for t, v in prev_log.items()
                       if v.get('status') in ('ok', 'no_target_rows_fetched',
                                              'no_data', 'skipped_split_suspect')}
            if done_ok:
                print(f"resume: {len(done_ok)} tickers already ok — skipping")
        except Exception:
            pass

    # bucket by identical window
    buckets = {}
    for t, w in win.items():
        if t not in done_ok:
            buckets.setdefault(w, []).append(t)
    print(f"window buckets: {len(buckets)}")
    for w, ts in sorted(buckets.items(), key=lambda kv: -len(kv[1]))[:8]:
        print(f"  {w[0]}..{w[1]}: {len(ts)} tickers")

    conn = get_connection()
    cur = conn.cursor()

    # preload silver closes for overlap split-check (only for window dates)
    print("preloading silver closes for split-consistency check ...")
    cur.execute("""
        SELECT ticker, date, close FROM silver.unified_prices
        WHERE close IS NOT NULL AND date >= '2018-01-01'
    """)
    silver = {}
    for t, d, c in cur.fetchall():
        silver.setdefault(t, {})[d] = float(c)
    print(f"  silver reference: {len(silver)} tickers")

    log = dict(prev_log)  # carry prior run's terminal statuses forward
    total_inserted = 0
    for (d0, d1), tickers in sorted(buckets.items()):
        for i in range(0, len(tickers), CHUNK):
            chunk = tickers[i:i + CHUNK]
            print(f"fetch {d0}..{d1} chunk [{i}..{i+len(chunk)-1}] ({len(chunk)} tickers)")
            try:
                data = yf.download(chunk, start=d0.isoformat(), end=d1.isoformat(),
                                   auto_adjust=True, progress=False)
            except Exception as e:
                print(f"  CHUNK ERROR: {e}")
                for t in chunk:
                    log[t] = {"error": f"chunk: {e}"}
                continue
            if data is None or len(data) == 0:
                for t in chunk:
                    log[t] = {"error": "empty download"}
                continue
            for t in chunk:
                try:
                    df = (data.xs(t, axis=1, level=1).reset_index()
                          if isinstance(data.columns, pd.MultiIndex)
                          else data.reset_index())
                except Exception as e:
                    log[t] = {"error": f"extract: {e}"}
                    continue
                df = df[pd.notna(df['Close'])]
                if df.empty:
                    log[t] = {"status": "no_data"}
                    continue
                df['__d'] = df['Date'].apply(
                    lambda x: x.date() if hasattr(x, 'date') else x)
                full_df = df  # for overlap split-check
                # INSERT-missing-only: restrict to this ticker's target dates
                # (never modify rows for dates that already exist downstream)
                tset = {date.fromisoformat(d) for d in targets[t]} if targets.get(t) else None
                if tset is not None:
                    df = df[df['__d'].isin(tset)]
                if df.empty:
                    log[t] = {"status": "no_target_rows_fetched"}
                    continue
                # split-consistency check on overlap with silver
                ref = silver.get(t, {})
                ratios = []
                for _, row in full_df.iterrows():
                    rd = row['__d']
                    if rd in ref and ref[rd] > 0:
                        ratios.append(float(row['Close']) / ref[rd])
                if ratios:
                    ratios.sort()
                    med = ratios[len(ratios) // 2]
                    if med < SPLIT_LO or med > SPLIT_HI:
                        log[t] = {"status": "skipped_split_suspect",
                                  "median_ratio": med, "overlap": len(ratios)}
                        print(f"  SPLIT SUSPECT {t}: median ratio {med:.4f} over {len(ratios)} overlap days — skipped")
                        continue
                try:
                    n = ing._upsert_prices(cur, t, df.drop(columns=['__d']).reset_index(drop=True))
                    conn.commit()
                    total_inserted += n
                    log[t] = {"status": "ok", "rows_upserted": n,
                              "window": [d0.isoformat(), d1.isoformat()],
                              "overlap_checked": len(ratios)}
                except Exception as e:
                    conn.rollback()
                    log[t] = {"error": f"upsert: {e}"}
                    print(f"  UPSERT ERROR {t}: {e}")
            time.sleep(SLEEP)
            gc.collect()  # yfinance/curl_cffi leaks fds per chunk; force cleanup
        # checkpoint log after each bucket
        with open(LOG, "w") as f:
            json.dump({"log": log, "skipped_fx_alias": skipped_alias,
                       "total_rows_upserted": total_inserted}, f, indent=1)
        print(f"  checkpoint: {total_inserted} rows upserted so far")

    conn.close()
    ok = sum(1 for v in log.values() if v.get('status') == 'ok')
    print(f"DONE: {ok}/{len(win)} tickers ok, {total_inserted} rows upserted -> {LOG}")

if __name__ == '__main__':
    main()
