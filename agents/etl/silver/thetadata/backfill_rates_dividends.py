#!/usr/bin/env python3
"""
Backfill inputs for the in-house deriv pricer (free sources, idempotent):

1. Risk-free rate: FRED DTB3 (3-Month T-Bill, secondary market, discount
   basis, pct) -> bronze.fred_macro_indicators. The platform table only held
   2025-11-17+; the deriv free window starts 2023-06-01. Fetched via the FRED
   API (key from qr_etl env; never printed/stored elsewhere).
   ON CONFLICT (series_id, date) DO NOTHING.

2. SPY cash dividends: Yahoo Finance chart API (events=div) ->
   deriv.underlying_dividends with source='YAHOO_CHART_API'. Needed because
   bronze.yf_prices.dividends is unpopulated and silver.unified_prices is
   back-adjusted (mixed vintage) so dividends cannot be derived in-house.
   ON CONFLICT (underlying, ex_date, source) DO NOTHING.

Run with /usr/bin/python3 (needs dotenv+psycopg2 via db.py).
"""
import datetime as dt
import json
import os
import sys
import urllib.request
import urllib.error

sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
from dotenv import load_dotenv  # noqa: E402
import db  # noqa: E402

load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'), override=True)

RATE_SERIES = [('DTB3', '3-Month Treasury Bill Rate', 'pct'),
               ('VIXCLS', 'CBOE Volatility Index: VIX', 'index')]
RATE_START = '2023-05-01'
DIV_UNDERLYING = 'SPY'
DIV_START = dt.date(2023, 1, 1)  # margin before window for TTM yield checks


def fetch_json(url: str, user_agent: str | None = None) -> dict:
    last = None
    for attempt in range(6):
        try:
            req = urllib.request.Request(
                url, headers={'User-Agent': user_agent} if user_agent else {})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 429:
                import time
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f'fetch failed after 6 attempts: {last}')


def backfill_rates(conn, series_id, indicator_name, units, obs) -> tuple:
    n = 0
    cur = conn.cursor()
    for o in obs:
        if o.get('value') in ('.', None, ''):
            continue
        cur.execute(
            """INSERT INTO bronze.fred_macro_indicators
               (series_id, indicator_name, units, frequency, date, value)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (series_id, date) DO NOTHING""",
            (series_id, indicator_name, units, 'daily',
             o['date'], float(o['value'])))
        n += cur.rowcount
    conn.commit()
    return n, len(obs)


def backfill_dividends(conn, divs) -> tuple:
    cur = conn.cursor()
    n = 0
    for _, d in sorted(divs.items()):
        ex = dt.datetime.utcfromtimestamp(int(d['date'])).date()
        cur.execute(
            """INSERT INTO deriv.underlying_dividends
               (underlying, ex_date, amount, source)
               VALUES (%s,%s,%s,'YAHOO_CHART_API')
               ON CONFLICT (underlying, ex_date, source) DO NOTHING""",
            (DIV_UNDERLYING, ex, round(float(d['amount']), 6)))
        n += cur.rowcount
    conn.commit()
    return n, len(divs)


def main():
    key = os.environ.get('FRED_API_KEY')
    if not key:
        sys.exit('FRED_API_KEY not in environment')
    # fetch everything BEFORE opening the DB connection
    series_obs = {}
    for sid, _, _ in RATE_SERIES:
        rates_url = ('https://api.stlouisfed.org/fred/series/observations'
                     f'?series_id={sid}&api_key={key}&file_type=json'
                     f'&observation_start={RATE_START}')
        series_obs[sid] = fetch_json(rates_url).get('observations', [])

    # dividends: skip fetch entirely if already populated (one-shot data)
    probe = db.get_connection()
    pcur = probe.cursor()
    pcur.execute("""SELECT count(*) FROM deriv.underlying_dividends
                    WHERE underlying=%s""", (DIV_UNDERLYING,))
    div_count = pcur.fetchone()[0]
    pcur.close()
    probe.close()
    divs = {}
    if div_count == 0:
        p1 = int(dt.datetime.combine(DIV_START, dt.time(0, 0)).timestamp())
        p2 = int(dt.datetime.now().timestamp())
        div_url = (f'https://query1.finance.yahoo.com/v8/finance/chart/{DIV_UNDERLYING}'
                   f'?period1={p1}&period2={p2}&interval=1d&events=div')
        divs = ((fetch_json(div_url, user_agent='Mozilla/5.0 (X11; Linux x86_64) '
                            'AppleWebKit/537.36 (KHTML, like Gecko) '
                            'Chrome/126.0 Safari/537.36')
                 ['chart']['result'][0].get('events') or {}).get('dividends', {}))
    else:
        print(f'DIVS {DIV_UNDERLYING}: already populated ({div_count} rows), skipping fetch')

    conn = db.get_connection()
    for sid, name, units in RATE_SERIES:
        ins_r, tot_r = backfill_rates(conn, sid, name, units, series_obs[sid])
        print(f'RATES {sid}: fetched={tot_r} inserted={ins_r}')
    ins_d, tot_d = backfill_dividends(conn, divs)
    print(f'DIVS {DIV_UNDERLYING}: fetched={tot_d} inserted={ins_d}')
    cur = conn.cursor()
    for sid, _, _ in RATE_SERIES:
        cur.execute("""SELECT min(date), max(date), count(*) FROM bronze.fred_macro_indicators
                       WHERE series_id=%s""", (sid,))
        print(f'{sid} coverage now:', cur.fetchone())
    cur.execute("""SELECT min(ex_date), max(ex_date), count(*) FROM deriv.underlying_dividends
                   WHERE underlying=%s""", (DIV_UNDERLYING,))
    print('SPY div coverage now:', cur.fetchone())
    conn.close()


if __name__ == '__main__':
    main()
