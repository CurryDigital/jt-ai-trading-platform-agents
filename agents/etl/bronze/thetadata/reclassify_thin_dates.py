#!/usr/bin/env python3
"""
Reclassify flagged thin dates (completeness-gate false positives) per the
2026-10-07 VERIFIED_THIN amendment.

For each flagged date (audit CSV, e.g. BACKFILL_AUDIT_2026-10-06.csv):
  1. If bronze already holds two pulls >=4h apart with identical row_count
     and distinct_contracts -> VERIFIED_THIN (no new vendor traffic).
  2. Else fresh-pull the date now (eod endpoint, same DTE filter as the
     backfill) and compare against the LATEST bronze pull:
       - identical            -> VERIFIED_THIN
       - fresh has MORE rows  -> REAL HOLE: insert fresh rows into bronze as a
                                 new run (label thin_reclassify), re-evaluate
                                 vs the gate baseline (VERIFIED or SHORT)
       - fresh has FEWER rows -> VENDOR SHRINK: stays SHORT, flagged loudly
  3. Bulk-fill VERIFIED for silver dates never flagged (above threshold at
     audit time) so the status table covers the whole loaded range.

Idempotent: dates already decided by this script (decided_by LIKE
'thin_reclassify%') are skipped on rerun. Commits per date.

Run with /usr/bin/python3 (psycopg2+dotenv). Requires the Theta Terminal.
  /usr/bin/python3 reclassify_thin_dates.py --csv <audit.csv> --yes
Use --limit N for a smoke test first.
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))

import db  # noqa: E402
from theta_client import ThetaClient, MarketClosed  # noqa: E402
from probe_pull import (ENDPOINTS, completeness_baseline, insert_rows,  # noqa: E402
                        record_completeness, record_short,
                        COMPLETENESS_MIN_RATIO)

LABEL = 'thin_reclassify_20261007'
REPORT = os.path.expanduser(
    '~/.hermes/profiles/qr_etl/workspace/deriv_options_schema_v1/'
    'THIN_RECLASSIFY_2026-10-07.csv')


def bronze_history(conn, symbol, dates):
    """Per-date list of pulls: (run_id, started_at, rows, contracts)."""
    cur = conn.cursor()
    cur.execute(
        """SELECT r.trade_date, run.ingest_run_id, run.started_at,
                  COUNT(*),
                  COUNT(DISTINCT (r.expiration, r.strike, r.option_right))
           FROM bronze.thetadata_option_eod_raw r
           JOIN bronze.thetadata_ingest_runs run USING (ingest_run_id)
           WHERE r.symbol = %s AND r.trade_date = ANY(%s::date[])
           GROUP BY 1,2,3 ORDER BY 1,3""",
        (symbol, dates))
    hist = {}
    for d, rid, started, rows, contracts in cur.fetchall():
        hist.setdefault(d.isoformat(), []).append(
            (str(rid), started, rows, contracts))
    cur.close()
    return hist


def stable_pair(pulls):
    """Two pulls >=4h apart with identical counts?"""
    for i in range(len(pulls)):
        for j in range(i + 1, len(pulls)):
            a, b = pulls[i], pulls[j]
            if abs((b[1] - a[1]).total_seconds()) >= 4 * 3600 \
                    and a[2] == b[2] and a[3] == b[3]:
                return a, b
    return None


def dte_filter(resp, date_str, min_dte, max_dte):
    d0 = dt.date.fromisoformat(date_str)
    return [r for r in resp
            if min_dte <= (dt.date.fromisoformat(r['contract']['expiration'])
                           - d0).days <= max_dte]


def counts(resp):
    return len(resp), len({(r['contract'].get('expiration'),
                            r['contract'].get('strike'),
                            r['contract'].get('right')) for r in resp})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--csv', required=True, help='audit CSV with trade_date col')
    ap.add_argument('--symbol', default='SPY')
    ap.add_argument('--min-dte', type=int, default=7)
    ap.add_argument('--max-dte', type=int, default=60)
    ap.add_argument('--limit', type=int, default=0, help='smoke test: first N dates needing fresh pulls')
    ap.add_argument('--yes', action='store_true', help='apply writes (default: dry-run)')
    args = ap.parse_args()

    flagged_rows = {r['trade_date']: r for r in csv.DictReader(open(args.csv))}
    flagged = list(flagged_rows)
    print(f'flagged dates: {len(flagged)}', flush=True)

    def csv_base(d):
        """Baseline medians from the audit CSV (fast; the live
        completeness_baseline query costs ~30-60s per date at this table
        size — only used on the rare REAL_HOLE path)."""
        r = flagged_rows.get(d, {})
        try:
            return (float(r['med_rows']), float(r['med_contracts']), None)
        except (KeyError, ValueError, TypeError):
            return None

    conn = db.get_connection()
    conn.autocommit = False
    endpoint, table = ENDPOINTS['eod']
    client = ThetaClient()

    # already decided by this script -> skip
    cur = conn.cursor()
    cur.execute("""SELECT trade_date FROM silver.thetadata_date_completeness
                   WHERE symbol=%s AND endpoint='eod'
                     AND decided_by LIKE %s""",
                (args.symbol, LABEL + '%'))
    done = {r[0].isoformat() for r in cur.fetchall()}
    cur.close()
    todo = [d for d in flagged if d not in done]
    print(f'already decided by {LABEL}: {len(done)}; todo: {len(todo)}', flush=True)

    hist = bronze_history(conn, args.symbol, todo)
    results = []
    n_fresh = 0

    for d in todo:
        pulls = hist.get(d, [])
        pair = stable_pair(pulls)
        if pair:
            a, b = pair
            note = f'bronze evidence: runs {a[0][:8]}@{a[1]} and {b[0][:8]}@{b[1]} identical'
            if args.yes:
                record_completeness(conn, args.symbol, 'eod', d, 'VERIFIED_THIN',
                                    a[2], a[3], csv_base(d), LABEL, note=note)
                conn.commit()
            print(f'{d}: VERIFIED_THIN (bronze evidence, rows={a[2]})', flush=True)
            results.append(dict(date=d, verdict='VERIFIED_THIN', fresh_rows='',
                                fresh_contracts='', stored_rows=a[2],
                                stored_contracts=a[3], note=note))
            continue

        if not pulls:
            print(f'{d}: ERROR no bronze history — skipped', flush=True)
            results.append(dict(date=d, verdict='ERROR', fresh_rows='',
                                fresh_contracts='', stored_rows='',
                                stored_contracts='', note='no bronze history'))
            continue

        latest = pulls[-1]
        if args.limit and n_fresh >= args.limit:
            continue
        n_fresh += 1
        t0 = dt.datetime.now()
        try:
            resp = client.option_eod(args.symbol, d)
        except MarketClosed:
            print(f'{d}: MARKET_CLOSED?? (has bronze rows) — skipped', flush=True)
            results.append(dict(date=d, verdict='ERROR', fresh_rows='',
                                fresh_contracts='', stored_rows=latest[2],
                                stored_contracts=latest[3],
                                note='vendor says market closed'))
            continue
        resp = dte_filter(resp, d, args.min_dte, args.max_dte)
        fr, fc = counts(resp)
        el = (dt.datetime.now() - t0).total_seconds()

        if fr == latest[2] and fc == latest[3]:
            verdict = 'VERIFIED_THIN'
            note = (f'stability re-pull {dt.date.today()} identical to run '
                    f'{latest[0][:8]}@{latest[1]}')
            if args.yes:
                record_completeness(conn, args.symbol, 'eod', d, 'VERIFIED_THIN',
                                    fr, fc, csv_base(d), LABEL, note=note)
                conn.commit()
        elif fr > latest[2] or fc > latest[3]:
            verdict = 'REAL_HOLE'
            note = (f'fresh pull MORE rows: {fr}/{fc} vs stored '
                    f'{latest[2]}/{latest[3]} (run {latest[0][:8]}@{latest[1]}); '
                    f'inserted under new run')
            print(f'{d}: *** REAL HOLE *** {note}', flush=True)
            if args.yes:
                cur = conn.cursor()
                cur.execute(
                    """INSERT INTO bronze.thetadata_ingest_runs
                       (loader, source_endpoint, request_params, finished_at,
                        status, rows_fetched, rows_inserted)
                       VALUES (%s,%s,%s,now(),'SUCCESS',%s,%s)
                       RETURNING ingest_run_id""",
                    ('reclassify_thin_dates.py', endpoint,
                     json.dumps({'label': LABEL, 'symbol': args.symbol,
                                 'date': d, 'min_dte': args.min_dte,
                                 'max_dte': args.max_dte, 'reason': note}),
                     fr, fr))
                run_id = cur.fetchone()[0]
                n_ins = insert_rows(cur, table, run_id, endpoint,
                                    {'label': LABEL}, args.symbol,
                                    'trade_date', d, resp)
                cur.close()
                # re-evaluate against the gate with the NEW counts
                base = completeness_baseline(conn, table, args.symbol, 'trade_date', d)
                if base and fr >= COMPLETENESS_MIN_RATIO * base[0] \
                        and fc >= COMPLETENESS_MIN_RATIO * base[1]:
                    record_completeness(conn, args.symbol, 'eod', d, 'VERIFIED',
                                        fr, fc, base, LABEL,
                                        note=note + '; passes gate after fill')
                else:
                    record_short(conn, args.symbol, 'eod', d, fr, fc, base,
                                 LABEL, None, dt.datetime.now(dt.timezone.utc))
                conn.commit()
                print(f'{d}: hole filled, bronze +{n_ins} rows, run {run_id}',
                      flush=True)
                note += f'; bronze run {run_id} (+{n_ins} rows)'
        else:
            verdict = 'VENDOR_SHRINK'
            note = (f'fresh pull FEWER rows: {fr}/{fc} vs stored '
                    f'{latest[2]}/{latest[3]} — left SHORT, investigate')
            if args.yes:
                record_short(conn, args.symbol, 'eod', d, fr, fc, csv_base(d),
                             LABEL, None, dt.datetime.now(dt.timezone.utc))
                conn.commit()

        print(f'{d}: {verdict} fresh={fr}/{fc} stored={latest[2]}/{latest[3]} '
              f'({el:.1f}s)', flush=True)
        results.append(dict(date=d, verdict=verdict, fresh_rows=fr,
                            fresh_contracts=fc, stored_rows=latest[2],
                            stored_contracts=latest[3], note=note))

    # bulk VERIFIED for never-flagged silver dates
    if args.yes and not args.limit:
        cur = conn.cursor()
        cur.execute(
            """WITH per_date AS (
                 SELECT q.trade_date, COUNT(*) AS rows,
                        COUNT(DISTINCT q.contract_id) AS contracts
                 FROM silver.option_eod_quotes q
                 JOIN silver.option_contracts c USING (contract_id)
                 WHERE c.underlying = %s GROUP BY 1)
               INSERT INTO silver.thetadata_date_completeness
                 (symbol, endpoint, trade_date, status, row_count,
                  distinct_contracts, decided_by, note)
               SELECT %s, 'eod', trade_date, 'VERIFIED', rows, contracts,
                      'audit_2026-10-06_backfill',
                      'at/above 0.95 trailing-20-median at audit 2026-10-06'
               FROM per_date
               WHERE trade_date <> ALL(%s::date[])
               ON CONFLICT (symbol, endpoint, trade_date) DO NOTHING""",
            (args.symbol, args.symbol, flagged))
        n_bulk = cur.rowcount
        conn.commit()
        cur.close()
        print(f'bulk VERIFIED backfill: {n_bulk} dates', flush=True)

    # report CSV (append mode for resume)
    write_header = not os.path.exists(REPORT)
    with open(REPORT, 'a', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['date', 'verdict', 'fresh_rows',
                                          'fresh_contracts', 'stored_rows',
                                          'stored_contracts', 'note'])
        if write_header:
            w.writeheader()
        for r in results:
            w.writerow(r)

    from collections import Counter
    print('VERDICTS:', dict(Counter(r['verdict'] for r in results)), flush=True)
    print(f'report: {REPORT}', flush=True)
    conn.close()


if __name__ == '__main__':
    main()
