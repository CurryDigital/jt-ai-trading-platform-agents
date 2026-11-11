#!/usr/bin/env python3
"""
ThetaData probe pull: vendor -> bronze raw tables.

- One ingest_run per invocation, recorded in bronze.thetadata_ingest_runs.
- Append-only: reruns insert under a NEW ingest_run_id, never rewrite.
- Resumable by date range: dates already present in bronze for (endpoint,
  symbol) under a SUCCESS run are skipped unless --force.
- Completeness gate (PRE-DECLARED 2026-10-05 in
  workspace/deriv_options_schema_v1/COMPLETENESS_GATE.md): a fetched date whose
  post-DTE-filter row count OR distinct-contract count is below 95% of the
  trailing-20-SUCCESS-date median is NOT inserted; the run finishes PARTIAL
  and the date is retried next run. Option endpoints only.
- --reverify-days N: re-fetch the N most recent SUCCESS-credited dates into
  the new run (vendor revision watch). Silver resolves keys to the latest
  ingest_run_id, so a revised answer supersedes; an identical answer is
  ignored downstream.
- Exit code: 0 all SUCCESS; 2 if any run ends PARTIAL/FAILED (cron alerts).
- Respects vendor rate limits via ThetaClient inter-request delay.
- Tier gates: a TierGated error marks the run FAILED with the vendor message;
  no partial fabrication.

Scope guard: --dates and --windows must be supplied explicitly; the loader
never pulls outside what the operator passes in.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))

from theta_client import ThetaClient, TierGated, MarketClosed  # noqa: E402
import db  # noqa: E402

# Completeness gate — pre-declared constants, see COMPLETENESS_GATE.md.
# Do NOT loosen after seeing results.
COMPLETENESS_MIN_RATIO = 0.95
COMPLETENESS_BASELINE_DATES = 20
COMPLETENESS_MIN_BASELINE = 5
# 2026-10-07 amendment (user directive): a SHORT date whose row_count AND
# distinct_contracts are identical across two pulls >= this many seconds apart
# is accepted as VERIFIED_THIN instead of retried/alerted forever.
STABILITY_MIN_GAP_S = 4 * 3600

ENDPOINTS = {
    'eod':    ('/v3/option/history/eod',           'bronze.thetadata_option_eod_raw'),
    'greeks': ('/v3/option/history/greeks/eod',    'bronze.thetadata_option_greeks_eod_raw'),
    'oi':     ('/v3/option/history/open_interest', 'bronze.thetadata_option_open_interest_raw'),
    'stock':  ('/v3/stock/history/eod',            'bronze.thetadata_stock_eod_raw'),
}


def sha(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def trading_days(start: str, end: str) -> list:
    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(end)
    days, d = [], d0
    while d <= d1:
        if d.weekday() < 5:
            days.append(d.isoformat())
        d += dt.timedelta(days=1)
    return days


def already_loaded(conn, table: str, symbol: str, date_col: str, dates: list,
                   label: "str | None" = None) -> set:
    """Dates with rows under a SUCCESS run (skip for resume).

    label=None: credit from ANY SUCCESS run (default, legacy behavior).
    label=<str>: credit only from SUCCESS runs whose request_params label
    matches — used by supplemental DTE-band pulls so their resume set is
    independent of the primary 7-60 band's credit."""
    cur = conn.cursor()
    if label is None:
        cur.execute(
            f"""SELECT DISTINCT r.{date_col} FROM {table} r
                JOIN bronze.thetadata_ingest_runs run USING (ingest_run_id)
                WHERE r.symbol = %s AND run.status = 'SUCCESS'
                  AND r.{date_col} = ANY(%s::date[])""",
            (symbol, dates))
    else:
        cur.execute(
            f"""SELECT DISTINCT r.{date_col} FROM {table} r
                JOIN bronze.thetadata_ingest_runs run USING (ingest_run_id)
                WHERE r.symbol = %s AND run.status = 'SUCCESS'
                  AND run.request_params->>'label' = %s
                  AND r.{date_col} = ANY(%s::date[])""",
            (symbol, label, dates))
    out = {row[0].isoformat() for row in cur.fetchall()}
    cur.close()
    return out


def insert_rows(cur, table: str, run_id: str, endpoint: str, params: dict,
                symbol: str, date_col: str, date_val: str, response: list) -> int:
    """Insert one day's response rows. Returns inserted count."""
    n = 0
    if table.endswith('stock_eod_raw'):
        rows = [(symbol, date_val, item) for item in response]
        for sym, d, payload in rows:
            cur.execute(
                f"""INSERT INTO {table}
                    (ingest_run_id, source_endpoint, request_params, symbol,
                     trade_date, payload, payload_hash)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (ingest_run_id, symbol, trade_date) DO NOTHING""",
                (run_id, endpoint, json.dumps(params), sym, d,
                 json.dumps(payload), sha(payload)))
            n += cur.rowcount
        return n
    for entry in response:
        c = entry.get('contract', {})
        data = entry.get('data') or []
        payload = {'contract': c, 'data': data}
        cur.execute(
            f"""INSERT INTO {table}
                (ingest_run_id, source_endpoint, request_params, symbol,
                 expiration, strike, option_right, {date_col}, payload, payload_hash)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING""",
            (run_id, endpoint, json.dumps(params), c.get('symbol', symbol),
             c.get('expiration'), c.get('strike'), c.get('right'),
             date_val, json.dumps(payload), sha(payload)))
        n += cur.rowcount
    return n


def completeness_baseline(conn, table: str, symbol: str, date_col: str,
                          before_date: str, endpoint: "str | None" = None):
    """Trailing credited-date medians (rows, distinct contracts) strictly
    before before_date — read from STORED per-date counts in
    silver.thetadata_date_completeness (VERIFIED / VERIFIED_THIN verdicts),
    NOT by re-scanning the raw quotes table. Same credited-date population
    and same median semantics as the old live scan; the live version cost
    30-60s/date at 2.7M rows and got its connection server-killed mid-
    backfill (2026-10-07, SPX_FULL at 2024-02-22). This lookup is ms."""
    ep = endpoint
    if ep is None:  # legacy callers: map raw table -> endpoint
        ep = {'bronze.thetadata_option_eod_raw': 'eod',
              'bronze.thetadata_option_greeks_eod_raw': 'greeks',
              'bronze.thetadata_option_open_interest_raw': 'oi'}.get(table)
    cur = conn.cursor()
    cur.execute(
        """SELECT row_count, distinct_contracts
           FROM silver.thetadata_date_completeness
           WHERE symbol = %s AND endpoint = %s AND trade_date < %s
             AND status IN ('VERIFIED', 'VERIFIED_THIN')
             AND row_count IS NOT NULL AND distinct_contracts IS NOT NULL
           ORDER BY trade_date DESC LIMIT %s""",
        (symbol, ep, before_date, COMPLETENESS_BASELINE_DATES))
    rows = cur.fetchall()
    cur.close()
    if len(rows) < COMPLETENESS_MIN_BASELINE:
        return None
    return (statistics.median(r[0] for r in rows),
            statistics.median(r[1] for r in rows),
            len(rows))


def get_completeness(conn, symbol: str, endpoint: str, trade_date: str):
    """Current completeness-gate record for a date, or None."""
    cur = conn.cursor()
    cur.execute(
        """SELECT status, row_count, distinct_contracts,
                  first_short_at, first_short_rows, first_short_contracts
           FROM silver.thetadata_date_completeness
           WHERE symbol=%s AND endpoint=%s AND trade_date=%s""",
        (symbol, endpoint, trade_date))
    row = cur.fetchone()
    cur.close()
    if not row:
        return None
    return {'status': row[0], 'row_count': row[1], 'distinct_contracts': row[2],
            'first_short_at': row[3], 'first_short_rows': row[4],
            'first_short_contracts': row[5]}


def record_completeness(conn, symbol: str, endpoint: str, trade_date: str,
                        status: str, n_rows: int, n_contracts: int, base,
                        decided_by: str, note=None):
    """Upsert a VERIFIED / VERIFIED_THIN verdict."""
    med_r = med_c = nb = None
    if base is not None:
        med_r, med_c, nb = base
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO silver.thetadata_date_completeness
             (symbol, endpoint, trade_date, status, row_count, distinct_contracts,
              baseline_med_rows, baseline_med_contracts, baseline_n,
              last_checked_at, decided_by, note)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s)
           ON CONFLICT (symbol, endpoint, trade_date) DO UPDATE SET
             status=EXCLUDED.status, row_count=EXCLUDED.row_count,
             distinct_contracts=EXCLUDED.distinct_contracts,
             baseline_med_rows=EXCLUDED.baseline_med_rows,
             baseline_med_contracts=EXCLUDED.baseline_med_contracts,
             baseline_n=EXCLUDED.baseline_n, last_checked_at=now(),
             decided_by=EXCLUDED.decided_by, note=EXCLUDED.note""",
        (symbol, endpoint, trade_date, status, n_rows, n_contracts,
         med_r, med_c, nb, decided_by, note))
    cur.close()


def record_short(conn, symbol: str, endpoint: str, trade_date: str,
                 n_rows: int, n_contracts: int, base, decided_by: str,
                 prev, now):
    """Upsert a SHORT verdict. The stability clock (first_short_*) restarts
    whenever there is no prior SHORT observation or the counts CHANGED —
    acceptance requires two IDENTICAL pulls >=4h apart."""
    med_r = med_c = nb = None
    if base is not None:
        med_r, med_c, nb = base
    reset = (prev is None or prev['status'] != 'SHORT'
             or prev['first_short_rows'] != n_rows
             or prev['first_short_contracts'] != n_contracts)
    if reset:
        first_at, fr, fc = now, n_rows, n_contracts
    else:
        assert prev is not None  # guaranteed: reset is True when prev is None
        first_at, fr, fc = (prev['first_short_at'], prev['first_short_rows'],
                            prev['first_short_contracts'])
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO silver.thetadata_date_completeness
             (symbol, endpoint, trade_date, status, row_count, distinct_contracts,
              baseline_med_rows, baseline_med_contracts, baseline_n,
              first_short_at, first_short_rows, first_short_contracts,
              last_checked_at, decided_by, note)
           VALUES (%s,%s,%s,'SHORT',%s,%s,%s,%s,%s,%s,%s,%s,now(),%s,%s)
           ON CONFLICT (symbol, endpoint, trade_date) DO UPDATE SET
             status='SHORT', row_count=EXCLUDED.row_count,
             distinct_contracts=EXCLUDED.distinct_contracts,
             baseline_med_rows=EXCLUDED.baseline_med_rows,
             baseline_med_contracts=EXCLUDED.baseline_med_contracts,
             baseline_n=EXCLUDED.baseline_n,
             first_short_at=EXCLUDED.first_short_at,
             first_short_rows=EXCLUDED.first_short_rows,
             first_short_contracts=EXCLUDED.first_short_contracts,
             last_checked_at=now(),
             decided_by=EXCLUDED.decided_by, note=EXCLUDED.note""",
        (symbol, endpoint, trade_date, n_rows, n_contracts, med_r, med_c, nb,
         first_at, fr, fc, decided_by,
         'awaiting identical second pull >=4h apart'))
    cur.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--symbol', required=True)
    ap.add_argument('--windows', nargs='+', required=True,
                    help='date windows START:END (inclusive), e.g. 2020-02-19:2020-03-23')
    ap.add_argument('--endpoints', default='eod,stock',
                    help='comma list of: eod,greeks,oi,stock')
    ap.add_argument('--min-dte', type=int, default=None)
    ap.add_argument('--max-dte', type=int, default=None)
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--label', default='probe')
    ap.add_argument('--reverify-days', type=int, default=0,
                    help='re-fetch the N most recent SUCCESS-credited dates '
                         '(vendor revision watch; revisions land as new run rows)')
    ap.add_argument('--no-gate', action='store_true',
                    help='skip the completeness gate entirely (no verdicts '
                         'recorded). For supplemental DTE-band pulls whose '
                         'row counts are not comparable to the primary band '
                         'baseline — recording SHORT there would corrupt '
                         'silver.thetadata_date_completeness.')
    ap.add_argument('--skip-same-label-only', action='store_true',
                    help='resume credit only from SUCCESS runs with the same '
                         '--label (supplemental DTE-band pulls); default '
                         'credits dates from ANY SUCCESS run.')
    args = ap.parse_args()

    endpoints = [e.strip() for e in args.endpoints.split(',') if e.strip()]
    for e in endpoints:
        if e not in ENDPOINTS:
            sys.exit(f'unknown endpoint {e}')

    client = ThetaClient()
    conn = db.get_connection()
    conn.autocommit = False
    cur = conn.cursor()

    log = {'symbol': args.symbol, 'windows': args.windows, 'endpoints': endpoints,
           'runs': []}

    for ep in endpoints:
        endpoint, table = ENDPOINTS[ep]
        date_col = 'report_date' if ep == 'oi' else 'trade_date'
        all_dates = []
        for w in args.windows:
            s, e = w.split(':')
            all_dates.extend(trading_days(s, e))
        all_dates = sorted(set(all_dates))

        skip = set() if args.force else already_loaded(
            conn, table, args.symbol, date_col, all_dates,
            label=args.label if args.skip_same_label_only else None)
        todo = [d for d in all_dates if d not in skip]

        # revision watch: re-fetch the N most recent SUCCESS-credited dates
        reverify = []
        if args.reverify_days > 0 and not args.force:
            cur.execute(
                f"""SELECT DISTINCT r.{date_col} FROM {table} r
                    JOIN bronze.thetadata_ingest_runs run USING (ingest_run_id)
                    WHERE r.symbol = %s AND run.status = 'SUCCESS'
                    ORDER BY 1 DESC LIMIT %s""",
                (args.symbol, args.reverify_days))
            reverify = [r[0].isoformat() for r in cur.fetchall()
                        if r[0].isoformat() not in todo]
            if reverify:
                todo.extend(reverify)
                todo.sort()
                print(f'[{ep}] reverify: {sorted(reverify)}', flush=True)

        print(f'[{ep}] {len(all_dates)} candidate days, {len(skip)} already loaded, '
              f'{len(todo)} to fetch', flush=True)
        if not todo:
            continue

        params = {'symbol': args.symbol, 'windows': args.windows, 'endpoint': endpoint,
                  'min_dte': args.min_dte, 'max_dte': args.max_dte, 'label': args.label,
                  'reverify_days': args.reverify_days}
        cur.execute(
            """INSERT INTO bronze.thetadata_ingest_runs
               (loader, source_endpoint, request_params) VALUES (%s,%s,%s)
               RETURNING ingest_run_id""",
            ('thetadata_probe_pull.py', endpoint, json.dumps(params)))
        run_id = cur.fetchone()[0]
        conn.commit()

        fetched = inserted = 0
        status, error = 'SUCCESS', None
        short_dates = []
        gate_enabled = ep in ('eod', 'greeks', 'oi') and not args.no_gate
        try:
            for d in todo:
                try:
                    if ep == 'eod':
                        resp = client.option_eod(args.symbol, d)
                    elif ep == 'greeks':
                        resp = client.option_greeks_eod(args.symbol, d)
                    elif ep == 'oi':
                        resp = client.option_open_interest(args.symbol, d)
                    else:
                        resp = client.stock_eod(args.symbol, d)
                except MarketClosed:
                    print(f'[{ep}] {d}: MARKET_CLOSED skip', flush=True)
                    continue

                # DTE filter (client-side, exact) for option endpoints
                if ep in ('eod', 'greeks', 'oi') and (args.min_dte is not None
                                                      or args.max_dte is not None):
                    dte_d = dt.date.fromisoformat(d)
                    lo = args.min_dte if args.min_dte is not None else -10**9
                    hi = args.max_dte if args.max_dte is not None else 10**9
                    resp = [r for r in resp
                            if lo <= (dt.date.fromisoformat(
                                r['contract']['expiration']) - dte_d).days <= hi]

                # completeness gate (pre-declared, COMPLETENESS_GATE.md)
                if gate_enabled:
                    base = completeness_baseline(conn, table, args.symbol,
                                                 date_col, d, endpoint=ep)
                    n_rows = len(resp)
                    n_contracts = len({(r['contract'].get('expiration'),
                                        r['contract'].get('strike'),
                                        r['contract'].get('right'))
                                       for r in resp})
                    if base is None:
                        # <5 baseline dates: pass with warning (pre-declared)
                        record_completeness(conn, args.symbol, ep, d, 'VERIFIED',
                                            n_rows, n_contracts, None,
                                            str(run_id),
                                            note='baseline <5 dates, pass-with-warning')
                    else:
                        med_rows, med_contracts, nbase = base
                        if (n_rows >= COMPLETENESS_MIN_RATIO * med_rows and
                                n_contracts >= COMPLETENESS_MIN_RATIO * med_contracts):
                            record_completeness(conn, args.symbol, ep, d,
                                                'VERIFIED', n_rows, n_contracts,
                                                base, str(run_id))
                        else:
                            # 2026-10-07 VERIFIED_THIN acceptance path:
                            # identical counts across two pulls >=4h apart
                            # => legitimate thin chain, accept and insert.
                            prev = get_completeness(conn, args.symbol, ep, d)
                            now = dt.datetime.now(dt.timezone.utc)
                            if prev and prev['status'] == 'VERIFIED_THIN' \
                                    and prev['row_count'] == n_rows \
                                    and prev['distinct_contracts'] == n_contracts:
                                # already accepted thin; counts unchanged
                                record_completeness(conn, args.symbol, ep, d,
                                                    'VERIFIED_THIN', n_rows,
                                                    n_contracts, base,
                                                    str(run_id),
                                                    note='re-confirmed thin')
                            elif prev and prev['status'] == 'SHORT' \
                                    and prev['first_short_at'] is not None \
                                    and (now - prev['first_short_at']).total_seconds() \
                                    >= STABILITY_MIN_GAP_S \
                                    and prev['first_short_rows'] == n_rows \
                                    and prev['first_short_contracts'] == n_contracts:
                                record_completeness(conn, args.symbol, ep, d,
                                                    'VERIFIED_THIN', n_rows,
                                                    n_contracts, base,
                                                    str(run_id),
                                                    note='stable across >=4h '
                                                         f'(first SHORT '
                                                         f'{prev["first_short_at"]})')
                                print(f'[{ep}] {d}: VERIFIED_THIN accepted '
                                      f'(rows={n_rows} vs median {med_rows:.0f}, '
                                      f'contracts={n_contracts} vs median '
                                      f'{med_contracts:.0f}) -- inserted',
                                      flush=True)
                            else:
                                record_short(conn, args.symbol, ep, d, n_rows,
                                             n_contracts, base, str(run_id),
                                             prev, now)
                                short_dates.append(
                                    f'{d} rows={n_rows}/{med_rows:.0f} '
                                    f'contracts={n_contracts}/{med_contracts:.0f}')
                                print(f'[{ep}] {d}: SHORT_CHAIN rejected '
                                      f'(rows={n_rows} vs median {med_rows:.0f}, '
                                      f'contracts={n_contracts} vs median '
                                      f'{med_contracts:.0f}, baseline n={nbase}) '
                                      f'-- NOT inserted, retried next run',
                                      flush=True)
                                continue

                fetched += len(resp)
                n = insert_rows(cur, table, run_id, endpoint, params, args.symbol,
                                date_col, d, resp)
                inserted += n
                conn.commit()
                print(f'[{ep}] {d}: fetched={len(resp)} inserted={n}', flush=True)
        except TierGated as e:
            status, error = 'FAILED', str(e)
            conn.rollback()
            print(f'[{ep}] TIER GATED: {e}', flush=True)
        except Exception as e:  # noqa: BLE001
            status, error = 'PARTIAL', str(e)[:500]
            conn.rollback()
            print(f'[{ep}] ERROR after {inserted} rows: {e}', flush=True)

        if short_dates and status == 'SUCCESS':
            status = 'PARTIAL'
            error = 'SHORT_CHAIN: ' + '; '.join(short_dates)
        elif short_dates and status == 'PARTIAL':
            error = (error or '') + ' | SHORT_CHAIN: ' + '; '.join(short_dates)

        cur.execute(
            """UPDATE bronze.thetadata_ingest_runs
               SET finished_at=now(), status=%s, rows_fetched=%s, rows_inserted=%s,
                   error=%s
               WHERE ingest_run_id=%s""",
            (status, fetched, inserted, error, run_id))
        conn.commit()
        log['runs'].append({'endpoint': ep, 'run_id': str(run_id), 'status': status,
                            'fetched': fetched, 'inserted': inserted, 'error': error})
        if status == 'FAILED':
            break  # tier gate: pointless to attempt remaining endpoints

    cur.close()
    conn.close()
    print(json.dumps(log, indent=2))
    bad = [r for r in log['runs'] if r['status'] != 'SUCCESS']
    if bad:
        print(f"ALERT: {len(bad)} run(s) not SUCCESS: "
              + '; '.join(f"{r['endpoint']}={r['status']}" for r in bad))
        sys.exit(2)


if __name__ == '__main__':
    main()
