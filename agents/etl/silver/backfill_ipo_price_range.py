#!/usr/bin/env python3
"""Batch driver: HK IPO price-range backfill from HKEXnews prospectuses.

Resumable via bronze.hkex_ipo_price_range_raw (one row per attempted IPO).
Threads: 4 workers, each with own requests session + DB connection.
Usage: runner.py [--retry-failures] [--limit N]
"""
import sys, os, time, threading, argparse
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))

import requests  # noqa: E402
from db import get_connection  # noqa: E402
from ipo_range_core import process_one, HEADERS  # noqa: E402

DDL_BRONZE = """
create table if not exists bronze.hkex_ipo_price_range_raw (
  ticker_code text not null,
  listing_date date not null,
  status text not null,
  low numeric, high numeric, fixed numeric,
  doc_url text, snippet text, error text,
  stock_id text, n_docs int,
  attempted_at timestamptz default now(),
  primary key (ticker_code, listing_date)
)"""
DDL_SILVER = """
alter table silver.unified_ipo_calendar
  add column if not exists price_range_source text,
  add column if not exists fixed_price boolean
"""

UPSERT_BRONZE = """
insert into bronze.hkex_ipo_price_range_raw
  (ticker_code, listing_date, status, low, high, fixed, doc_url, snippet, error, stock_id, n_docs, attempted_at)
values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
on conflict (ticker_code, listing_date) do update set
  status=excluded.status, low=excluded.low, high=excluded.high, fixed=excluded.fixed,
  doc_url=excluded.doc_url, snippet=excluded.snippet, error=excluded.error,
  stock_id=excluded.stock_id, n_docs=excluded.n_docs, attempted_at=now()
"""
UPDATE_SILVER_OK = """
update silver.unified_ipo_calendar set
  offer_price_low=%s, offer_price_high=%s,
  price_range_source='hkexnews_prospectus', fixed_price=false, updated_at=now()
where ticker=%s and listing_date=%s
"""
UPDATE_SILVER_FIXED = """
update silver.unified_ipo_calendar set
  offer_price_low=null, offer_price_high=null,
  price_range_source='hkexnews_prospectus', fixed_price=true, updated_at=now()
where ticker=%s and listing_date=%s
"""
UPDATE_SILVER_MAXONLY = """
update silver.unified_ipo_calendar set
  offer_price_low=null, offer_price_high=%s,
  price_range_source='hkexnews_prospectus_max_only', fixed_price=false, updated_at=now()
where ticker=%s and listing_date=%s
"""
UPDATE_SILVER_MKTCAP = """
update silver.unified_ipo_calendar set
  offer_price_low=%s, offer_price_high=%s,
  price_range_source='hkexnews_prospectus_mktcap_table', fixed_price=false, updated_at=now()
where ticker=%s and listing_date=%s
"""

print_lock = threading.Lock()
counter = {'done': 0, 'ok': 0, 'fixed': 0}


def log(msg):
    with print_lock:
        print(msg, flush=True)


def ticker_to_code(t):
    return t.split('.')[0].zfill(5)


def work(item):
    ticker, ld = item
    code = ticker_to_code(ticker)
    sess = requests.Session(); sess.headers.update(HEADERS)
    con = get_connection(); con.autocommit = True
    try:
        r = process_one(sess, code, ld)
        cur = con.cursor()
        cur.execute(UPSERT_BRONZE, (code, ld, r['status'], r.get('low'), r.get('high'),
                                    r.get('fixed'), r.get('doc_url'), r.get('snippet'),
                                    r.get('error'), r.get('stock_id'), r.get('n_docs')))
        if r['status'] == 'ok':
            cur.execute(UPDATE_SILVER_OK, (r['low'], r['high'], ticker, ld))
        elif r['status'] == 'ok_mktcap':
            cur.execute(UPDATE_SILVER_MKTCAP, (r['low'], r['high'], ticker, ld))
        elif r['status'] == 'fixed':
            cur.execute(UPDATE_SILVER_FIXED, (ticker, ld))
        elif r['status'] == 'max_only':
            cur.execute(UPDATE_SILVER_MAXONLY, (r['fixed'], ticker, ld))
        with print_lock:
            counter['done'] += 1
            counter[r['status'] if r['status'] in ('ok', 'fixed') else 'done'] += 0
            if r['status'] in ('ok', 'ok_mktcap'):
                counter['ok'] += 1
            elif r['status'] in ('fixed', 'max_only'):
                counter['fixed'] += 1
            n = counter['done']
        if r['status'] not in ('ok', 'ok_mktcap', 'fixed', 'max_only'):
            log(f"  [{n}] {ticker} {ld} -> {r['status']} {str(r.get('error'))[:120]}")
        elif n % 50 == 0:
            log(f"  [{n}] progress: ok={counter['ok']} fixed={counter['fixed']}")
        time.sleep(0.4)  # be polite to hkexnews
    except Exception as e:
        log(f"  WORKER-ERR {ticker}: {str(e)[:200]}")
    finally:
        con.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--retry-failures', action='store_true')
    ap.add_argument('--only', default='', help='comma list of bronze statuses to retry')
    ap.add_argument('--limit', type=int, default=0)
    args = ap.parse_args()

    con = get_connection(); con.autocommit = True
    cur = con.cursor()
    cur.execute(DDL_BRONZE)
    cur.execute(DDL_SILVER)

    resume_key = "lpad(split_part(c.ticker,'.',1),5,'0')"
    if args.only:
        sts = tuple(s.strip() for s in args.only.split(','))
        cur.execute(f"""select ticker, listing_date from silver.unified_ipo_calendar c
            where exists (select 1 from bronze.hkex_ipo_price_range_raw b
              where b.ticker_code = {resume_key} and b.listing_date=c.listing_date
                and b.status in %s)
            order by c.listing_date""", (sts,))
    elif args.retry_failures:
        cur.execute(f"""select ticker, listing_date from silver.unified_ipo_calendar c
            where not exists (select 1 from bronze.hkex_ipo_price_range_raw b
              where b.ticker_code = {resume_key} and b.listing_date=c.listing_date
                and b.status in ('ok','ok_mktcap','fixed','max_only'))
            order by c.listing_date""")
    else:
        cur.execute(f"""select ticker, listing_date from silver.unified_ipo_calendar c
            where not exists (select 1 from bronze.hkex_ipo_price_range_raw b
              where b.ticker_code = {resume_key} and b.listing_date=c.listing_date)
            order by c.listing_date""")
    todo = cur.fetchall()
    if args.limit:
        todo = todo[:args.limit]
    print(f'todo: {len(todo)} IPOs', flush=True)
    con.close()

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(work, todo))
    dt = time.time() - t0
    print(f'DONE in {round(dt/60,1)}min: processed={counter["done"]} ok={counter["ok"]} fixed={counter["fixed"]}', flush=True)


if __name__ == '__main__':
    main()
