#!/usr/bin/env python3
"""refresh_ipo_allotment_daily.py — keep HK IPO allotment results current.

Kanban t_49215d54. Allotment-results announcements publish 1-2 days BEFORE
listing. Each run processes IPOs listing in [today-12d, today+3d] that do not
yet have a good bronze.hkex_ipo_allotment_raw row, using the same parser and
upserts as silver/backfill_ipo_allotment.py (which owns the full history).

Runs in Pipeline A after refresh_ipo_upcoming_daily.py. Idempotent.
"""
import sys, os, json, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import requests  # noqa: E402
from db import get_connection  # noqa: E402
from ipo_allotment_core import process_one, HEADERS  # noqa: E402
from backfill_ipo_allotment import (  # noqa: E402
    DDL_BRONZE, DDL_SILVER, UPSERT_BRONZE, UPSERT_SILVER, GOOD, ticker_to_code)

WINDOW_SQL = """
select ticker, listing_date from silver.unified_ipo_calendar c
where c.listing_date between current_date - 12 and current_date + 3
  and not exists (select 1 from bronze.hkex_ipo_allotment_raw b
    where b.ticker_code = lpad(split_part(c.ticker,'.',1),5,'0')
      and b.listing_date = c.listing_date
      and b.status in ('ok','partial_summary','partial_table'))
order by c.listing_date
"""


def main():
    con = get_connection(); con.autocommit = True
    cur = con.cursor()
    cur.execute(DDL_BRONZE)
    cur.execute(DDL_SILVER)
    cur.execute(WINDOW_SQL)
    todo = cur.fetchall()
    print(f'allotment refresh: {len(todo)} IPOs in window pending', flush=True)
    n_ok = 0
    sess = requests.Session(); sess.headers.update(HEADERS)
    for ticker, ld in todo:
        code = ticker_to_code(ticker)
        r = process_one(sess, code, ld)
        payload = {k: v for k, v in r.items()
                   if k not in ('snippet', 'error', 'doc_title')}
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
            n_ok += 1
        else:
            print(f'  {ticker} {ld} -> {r["status"]} '
                  f'{str(r.get("error") or "")[:100]}', flush=True)
        time.sleep(0.4)
    con.close()
    print(f'DONE: {n_ok}/{len(todo)} landed', flush=True)


if __name__ == '__main__':
    main()
