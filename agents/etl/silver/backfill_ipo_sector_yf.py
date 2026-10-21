#!/usr/bin/env python3
"""
Silver: backfill sector/sub_sector on silver.unified_ipo_calendar via yfinance
(kanban t_2f98c3be, 2026-09-02)

Why: gold.hk_ipo_calendar.sector is NULL for ~83% of rows (2y window: ~97%).
Root cause: the only sector source was the GEM New Listing Report; main-board
NLR and AAStocks carry no sector. yfinance Ticker.info provides GICS-style
sector/industry for live .HK tickers (~12/12 hit rate probed 2026-09-02).

Taxonomy note: existing values from hkex_nlr_gem use "Sector - Industry"
(HKEX-style, e.g. "Information Technology - Software & Services"); yfinance
backfill writes GICS-style sector into `sector` and industry into
`sub_sector` (e.g. sector="Technology", sub_sector="Semiconductors").
Provenance tagged by appending '+yfsector' to data_source.

Resumable: only selects rows where sector IS NULL. Delisted/GEM tickers with
no yfinance page are left NULL (structural gap).

Run:  /home/ubuntu/.hermes/etl-venv/bin/python backfill_ipo_sector_yf.py
"""
import sys, os, time, threading
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed

WORKERS = 6
BATCH_COMMIT = 100

_local = threading.local()

def fetch_sector(ticker):
    code = ticker.replace('.HK', '').zfill(4) + '.HK'
    try:
        info = yf.Ticker(code).info
        sec = (info.get('sector') or '')[:100] or None
        ind = (info.get('industry') or '')[:100] or None
        return sec, ind
    except Exception:
        return None, None

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""SELECT id, ticker FROM silver.unified_ipo_calendar
                   WHERE sector IS NULL ORDER BY listing_date DESC""")
    rows = cur.fetchall()
    total = len(rows)
    print(f"NULL-sector rows to attempt: {total}", flush=True)
    if not rows:
        print("nothing to do"); return

    done = updated = 0
    t0 = time.time()
    pending = []
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fetch_sector, t): (rid, t) for rid, t in rows}
        for fut in as_completed(futs):
            rid, ticker = futs[fut]
            sec, ind = fut.result()
            done += 1
            if sec:
                pending.append((sec, ind, rid))
                updated += 1
            if len(pending) >= BATCH_COMMIT:
                cur.executemany("""UPDATE silver.unified_ipo_calendar
                                   SET sector=%s, sub_sector=%s,
                                       data_source = COALESCE(data_source,'') || '+yfsector',
                                       updated_at=NOW()
                                   WHERE id=%s AND sector IS NULL""", pending)
                conn.commit()
                pending.clear()
            if done % 100 == 0:
                rate = done / max(time.time() - t0, 1)
                print(f"{done}/{total} attempted, {updated} sectors found, {rate:.1f}/s", flush=True)
    if pending:
        cur.executemany("""UPDATE silver.unified_ipo_calendar
                           SET sector=%s, sub_sector=%s,
                               data_source = COALESCE(data_source,'') || '+yfsector',
                               updated_at=NOW()
                           WHERE id=%s AND sector IS NULL""", pending)
        conn.commit()
    print(f"DONE: {done} attempted, {updated} sectors backfilled in {time.time()-t0:.0f}s", flush=True)
    cur.close(); conn.close()

if __name__ == '__main__':
    run()
