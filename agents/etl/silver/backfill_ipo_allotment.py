#!/usr/bin/env python3
"""backfill_ipo_allotment.py — HK IPO allotment results backfill (2024+).

Kanban t_49215d54. Fetches HKEXnews "ALLOTMENT RESULTS" announcements for
every silver.unified_ipo_calendar IPO listed 2024-01-01..today and lands:
  bronze.hkex_ipo_allotment_raw  (resumable audit; one row per attempt)
  silver.hk_ipo_allotment        (one_lot_win_rate, pool A/B tier tables,
                                  clawback + final retail tranche, oversub)

Resumable: skips tickers already 'ok'/'partial_*' in bronze unless
--retry-failures / --only is given. 4 threads, 0.4s polite delay.

Usage:
  backfill_ipo_allotment.py [--limit N] [--retry-failures] [--only a,b,c]
                            [--all-history]   (default universe: 2024+)
"""
import sys, os, time, json, threading, argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import requests  # noqa: E402
from db import get_connection  # noqa: E402
from ipo_allotment_core import process_one, HEADERS  # noqa: E402

DDL_BRONZE = """
create table if not exists bronze.hkex_ipo_allotment_raw (
  ticker_code text not null,
  listing_date date not null,
  status text not null,
  payload jsonb,
  doc_url text, doc_title text, snippet text, error text,
  stock_id text, n_docs int,
  attempted_at timestamptz default now(),
  primary key (ticker_code, listing_date)
)"""
DDL_SILVER = """
create table if not exists silver.hk_ipo_allotment (
  ticker varchar(10) not null,
  listing_date date not null,
  one_lot_win_rate numeric(8,2),
  allotment_table jsonb,
  retail_valid_applications integer,
  retail_successful_applications integer,
  oversub_retail_ann numeric(14,2),
  oversub_intl_ann numeric(14,2),
  clawback_triggered boolean,
  retail_shares_initial bigint,
  retail_shares_reallocated bigint,
  retail_shares_final bigint,
  retail_pct_final numeric(6,2),
  source_url text,
  parse_status text not null,
  scraped_at timestamptz default now(),
  primary key (ticker, listing_date)
)"""

UPSERT_BRONZE = """
insert into bronze.hkex_ipo_allotment_raw
  (ticker_code, listing_date, status, payload, doc_url, doc_title,
   snippet, error, stock_id, n_docs, attempted_at)
values (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s, now())
on conflict (ticker_code, listing_date) do update set
  status=excluded.status, payload=excluded.payload, doc_url=excluded.doc_url,
  doc_title=excluded.doc_title, snippet=excluded.snippet, error=excluded.error,
  stock_id=excluded.stock_id, n_docs=excluded.n_docs, attempted_at=now()
"""
UPSERT_SILVER = """
insert into silver.hk_ipo_allotment
  (ticker, listing_date, one_lot_win_rate, allotment_table,
   retail_valid_applications, retail_successful_applications,
   oversub_retail_ann, oversub_intl_ann, clawback_triggered,
   retail_shares_initial, retail_shares_reallocated, retail_shares_final,
   retail_pct_final, source_url, parse_status, scraped_at)
values (%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
on conflict (ticker, listing_date) do update set
  one_lot_win_rate=excluded.one_lot_win_rate,
  allotment_table=excluded.allotment_table,
  retail_valid_applications=excluded.retail_valid_applications,
  retail_successful_applications=excluded.retail_successful_applications,
  oversub_retail_ann=excluded.oversub_retail_ann,
  oversub_intl_ann=excluded.oversub_intl_ann,
  clawback_triggered=excluded.clawback_triggered,
  retail_shares_initial=excluded.retail_shares_initial,
  retail_shares_reallocated=excluded.retail_shares_reallocated,
  retail_shares_final=excluded.retail_shares_final,
  retail_pct_final=excluded.retail_pct_final,
  source_url=excluded.source_url,
  parse_status=excluded.parse_status, scraped_at=now()
"""

GOOD = ('ok', 'partial_summary', 'partial_table')
print_lock = threading.Lock()
counter = {'done': 0}


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
        payload = {k: v for k, v in r.items()
                   if k not in ('snippet', 'error', 'doc_title')}
        cur = con.cursor()
        cur.execute(UPSERT_BRONZE,
                    (code, ld, r['status'], json.dumps(payload, default=str),
                     r.get('doc_url'), r.get('doc_title'), r.get('snippet'),
                     r.get('error'), r.get('stock_id'), r.get('n_docs')))
        if r['status'] in GOOD:
            table = {}
            if r.get('pool_a'):
                table['pool_a'] = r['pool_a']
            if r.get('pool_b'):
                table['pool_b'] = r['pool_b']
            cur.execute(UPSERT_SILVER,
                        (ticker, ld, r.get('one_lot_win_rate'),
                         json.dumps(table) if table else None,
                         r.get('retail_valid_applications'),
                         r.get('retail_successful_applications'),
                         r.get('oversub_retail_ann'), r.get('oversub_intl_ann'),
                         r.get('clawback_triggered'),
                         r.get('retail_shares_initial'),
                         r.get('retail_shares_reallocated'),
                         r.get('retail_shares_final'),
                         r.get('retail_pct_final'), r.get('doc_url'),
                         r['status']))
        with print_lock:
            counter['done'] += 1
            n = counter['done']
        if r['status'] not in GOOD:
            log(f"  [{n}] {ticker} {ld} -> {r['status']} "
                f"{str(r.get('error') or '')[:120]}")
        elif n % 25 == 0:
            log(f"  [{n}] progress")
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
    ap.add_argument('--all-history', action='store_true',
                    help='whole calendar instead of 2024+')
    args = ap.parse_args()

    con = get_connection(); con.autocommit = True
    cur = con.cursor()
    cur.execute(DDL_BRONZE)
    cur.execute(DDL_SILVER)

    resume_key = "lpad(split_part(c.ticker,'.',1),5,'0')"
    date_filter = "" if args.all_history else "and c.listing_date >= date '2024-01-01'"
    base_where = (f"c.listing_date <= current_date {date_filter}")
    if args.only:
        sts = tuple(s.strip() for s in args.only.split(','))
        cur.execute(f"""select ticker, listing_date from silver.unified_ipo_calendar c
            where {base_where} and exists (select 1 from bronze.hkex_ipo_allotment_raw b
              where b.ticker_code = {resume_key} and b.listing_date=c.listing_date
                and b.status in %s)
            order by c.listing_date""", (sts,))
    elif args.retry_failures:
        cur.execute(f"""select ticker, listing_date from silver.unified_ipo_calendar c
            where {base_where} and not exists (select 1 from bronze.hkex_ipo_allotment_raw b
              where b.ticker_code = {resume_key} and b.listing_date=c.listing_date
                and b.status in ('ok','partial_summary','partial_table'))
            order by c.listing_date""")
    else:
        cur.execute(f"""select ticker, listing_date from silver.unified_ipo_calendar c
            where {base_where} and not exists (select 1 from bronze.hkex_ipo_allotment_raw b
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
    print(f'DONE in {round(dt/60,1)}min: processed={counter["done"]}', flush=True)


if __name__ == '__main__':
    main()
