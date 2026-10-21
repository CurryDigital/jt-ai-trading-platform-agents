#!/usr/bin/env python3
"""
bronze -> silver loader for ThetaData options.

Revision model (2026-10-05, user directive):
- Silver resolves every natural key to the LATEST ingest_run_id
  (bronze.thetadata_ingest_runs.started_at). This replaces the original
  first-loaded-wins ON CONFLICT DO NOTHING. A newer revision of an existing
  (contract_id, trade_date) UPDATES the row and moves lineage.
- 2026-10-06 amendment (user directive): a newer revision whose values are
  IDENTICAL to the stored row is a no-op — the row is NOT rewritten, lineage
  is NOT moved, and greeks are NOT invalidated. 'updated' counts only rows
  where bid/ask/mid/sizes/volume/trade_count/underlying_close actually
  differ. (last_trade_at / report_created_at are vendor metadata and do not
  trigger rewrites; quality_flags derive from bid/ask/volume.)
- Quote revisions invalidate the matching COMPUTED greeks rows
  (silver.option_eod_greeks greek_source='COMPUTED' deleted for revised
  keys); computed_greeks.py recomputes them incrementally afterwards.
- open_interest is NOT touched by quote revisions (owned by the OI endpoint).

Incremental by default: only processes ingest runs not yet recorded in
silver.thetadata_load_ledger (migration 2026-10-05). Per-run reconciliation:
bronze rows for the run == inserted + updated + already_current + bad.

--full: reprocesses ALL runs for the symbol and runs the global
reconciliation (bronze distinct natural keys == silver rows). Weekly cron
job; also the escape hatch after schema changes.

Usage: load_silver.py [--symbol SPY] [--run-id UUID | --full]
"""
import argparse
import datetime as dt
import json
import os
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
import db  # noqa: E402

ET = ZoneInfo('America/New_York')

EOD_ENDPOINT = '/v3/option/history/eod'
GREEKS_ENDPOINT = '/v3/option/history/greeks/eod'

# exercise_style / settlement / multiplier per underlying — explicit, never assumed
UNDERLYING_SPEC = {
    'SPY': ('AMERICAN', 'PHYSICAL', 100),
    'QQQ': ('AMERICAN', 'PHYSICAL', 100),
    'IWM': ('AMERICAN', 'PHYSICAL', 100),
    'SPX': ('EUROPEAN', 'CASH', 100),
    'VIX': ('EUROPEAN', 'CASH', 100),
}
DEFAULT_SPEC = ('AMERICAN', 'PHYSICAL', 100)


def occ_symbol(underlying: str, expiry: dt.date, strike, right_word: str) -> str:
    """OCC/OPRA symbology: root(6, space-padded) + yymmdd + C/P + strike*1000(8)."""
    root = underlying.upper().ljust(6)[:6]
    ymd = expiry.strftime('%y%m%d')
    cp = 'C' if right_word.upper().startswith('C') else 'P'
    k = int(round(float(strike) * 1000))
    return f'{root}{ymd}{cp}{k:08d}'


def et_ts(s):
    if not s:
        return None
    naive = dt.datetime.fromisoformat(s)
    return naive.replace(tzinfo=ET)


def quality_flags(bid, ask, volume) -> list:
    flags = []
    b = float(bid or 0)
    a = float(ask or 0)
    if b == 0:
        flags.append('ZERO_BID')
    if b > 0 and a > 0 and b > a:
        flags.append('CROSSED')
    if a > 0 and b >= 0 and b <= a:
        mid = (a + b) / 2
        if mid > 0 and (a - b) / mid > 0.10:
            flags.append('WIDE_SPREAD')
    if not volume:
        flags.append('NO_TRADES')
    return flags


def runs_in_scope(cur, symbol, endpoint, run_filter, full):
    """Unprocessed (or all, with --full) ingest runs for symbol+endpoint."""
    where = "source_endpoint = %s AND rows_inserted > 0 AND loader = 'thetadata_probe_pull.py'"
    params = [endpoint]
    if symbol:
        where += " AND request_params->>'symbol' = %s"
        params.append(symbol)
    if run_filter:
        where += " AND ingest_run_id = %s"
        params.append(run_filter)
    elif not full:
        where += (" AND ingest_run_id NOT IN "
                  "(SELECT ingest_run_id FROM silver.thetadata_load_ledger)")
    cur.execute(
        f"""SELECT ingest_run_id, started_at, status FROM bronze.thetadata_ingest_runs
            WHERE {where} ORDER BY started_at""", params)
    return cur.fetchall()


def load_quotes(conn, symbol, run_filter, full) -> dict:
    cur = conn.cursor()
    runs = runs_in_scope(cur, symbol, EOD_ENDPOINT, run_filter, full)
    if not runs:
        print('[quotes] no new ingest runs to process')
        return {'runs_processed': 0}
    run_ids = [r[0] for r in runs]
    print(f'[quotes] processing {len(runs)} ingest run(s):')
    for rid, started, status in runs:
        print(f'  {rid} {status} {started}')

    # underlying closes: latest run per date wins for reading
    cur.execute(
        """SELECT DISTINCT ON (symbol, trade_date) symbol, trade_date, payload
           FROM bronze.thetadata_stock_eod_raw ORDER BY symbol, trade_date, ingested_at DESC""")
    uclose = {(s, d): (p.get('close')) for s, d, p in cur.fetchall()}

    cur.execute("DROP TABLE IF EXISTS qbatch")
    cur.execute("""
        CREATE TEMP TABLE qbatch (
            contract_id bigint, trade_date date, bid numeric, ask numeric,
            mid numeric, bid_size integer, ask_size integer, volume integer,
            trade_count integer, underlying_close numeric,
            last_trade_at timestamptz, report_created_at timestamptz,
            quality_flags text[], ingest_run_id uuid, run_started timestamptz
        )""")

    from psycopg2.extras import execute_values

    scur = conn.cursor(name='silver_quote_stream')
    scur.itersize = 2000
    scur.execute(
        """SELECT r.ingest_run_id, r.symbol, r.expiration, r.strike, r.option_right,
                  r.trade_date, r.payload, run.started_at
           FROM bronze.thetadata_option_eod_raw r
           JOIN bronze.thetadata_ingest_runs run USING (ingest_run_id)
           WHERE r.ingest_run_id = ANY(%s::uuid[])
           ORDER BY r.trade_date, r.ingest_run_id""", (run_ids,))

    contracts_upserted = 0
    per_run = {str(rid): {'bronze': 0, 'inserted': 0, 'updated': 0,
                          'already_current': 0, 'bad': 0} for rid in run_ids}
    updated_keys = []            # (contract_id, trade_date) revised to newer run
    contract_cache = {}
    contract_span = {}
    quote_buf = []

    def flush_quotes():
        if not quote_buf:
            return
        cur.execute('TRUNCATE qbatch')
        execute_values(cur, "INSERT INTO qbatch VALUES %s",
                       quote_buf, page_size=5000)
        # one winner per natural key inside the batch: latest run
        cur.execute('DROP TABLE IF EXISTS qdedup')
        cur.execute("""
            CREATE TEMP TABLE qdedup AS
            SELECT DISTINCT ON (contract_id, trade_date) * FROM qbatch
            ORDER BY contract_id, trade_date, run_started DESC""")
        # in-batch losers (older revision of a key also present in qbatch):
        # count as already_current for their run so per-run recon balances
        cur.execute('SELECT ingest_run_id, COUNT(*) FROM qbatch GROUP BY 1')
        batch_n = {str(r): n for r, n in cur.fetchall()}
        cur.execute('SELECT ingest_run_id, COUNT(*) FROM qdedup GROUP BY 1')
        dedup_n = {str(r): n for r, n in cur.fetchall()}
        for rid, n in batch_n.items():
            per_run[rid]['already_current'] += n - dedup_n.get(rid, 0)
        # keys that already exist in silver; a NEWER revision replaces only
        # when values actually changed (no-op rewrites banned 2026-10-06)
        cur.execute("""
            SELECT t.contract_id, t.trade_date
            FROM qdedup t
            JOIN silver.option_eod_quotes q USING (contract_id, trade_date)""")
        existing_keys = set(cur.fetchall())
        cur.execute("""
            SELECT t.contract_id, t.trade_date, t.ingest_run_id
            FROM qdedup t
            JOIN silver.option_eod_quotes q USING (contract_id, trade_date)
            JOIN bronze.thetadata_ingest_runs r_old ON r_old.ingest_run_id = q.ingest_run_id
            WHERE t.run_started > r_old.started_at
              AND (t.bid::numeric(14,6) IS DISTINCT FROM q.bid
                OR t.ask::numeric(14,6) IS DISTINCT FROM q.ask
                OR t.mid::numeric(14,6) IS DISTINCT FROM q.mid
                OR t.bid_size IS DISTINCT FROM q.bid_size
                OR t.ask_size IS DISTINCT FROM q.ask_size
                OR t.volume IS DISTINCT FROM q.volume
                OR t.trade_count IS DISTINCT FROM q.trade_count
                OR t.underlying_close::numeric(14,6) IS DISTINCT FROM q.underlying_close)""")
        upd = set()
        for c, d, rid in cur.fetchall():
            upd.add((c, d))
            per_run[str(rid)]['updated'] += 1
            updated_keys.append((c, d))
        cur.execute('SELECT contract_id, trade_date, ingest_run_id FROM qdedup')
        for c, d, rid in cur.fetchall():
            if (c, d) in upd:
                continue
            if (c, d) in existing_keys:
                per_run[str(rid)]['already_current'] += 1
            else:
                per_run[str(rid)]['inserted'] += 1
        # latest-wins upsert; the rewrite fires only for a NEWER run whose
        # values genuinely differ (no-op revisions skip the row entirely)
        cur.execute("""
            INSERT INTO silver.option_eod_quotes
               (contract_id, trade_date, bid, ask, mid, bid_size, ask_size, volume,
                trade_count, open_interest, underlying_close, last_trade_at,
                report_created_at, quality_flags, ingest_run_id)
            SELECT contract_id, trade_date, bid, ask, mid, bid_size, ask_size,
                   volume, trade_count, NULL, underlying_close, last_trade_at,
                   report_created_at, quality_flags, ingest_run_id
            FROM qdedup
            ON CONFLICT (contract_id, trade_date) DO UPDATE SET
                bid = EXCLUDED.bid, ask = EXCLUDED.ask, mid = EXCLUDED.mid,
                bid_size = EXCLUDED.bid_size, ask_size = EXCLUDED.ask_size,
                volume = EXCLUDED.volume, trade_count = EXCLUDED.trade_count,
                underlying_close = EXCLUDED.underlying_close,
                last_trade_at = EXCLUDED.last_trade_at,
                report_created_at = EXCLUDED.report_created_at,
                quality_flags = EXCLUDED.quality_flags,
                ingest_run_id = EXCLUDED.ingest_run_id
            WHERE (SELECT started_at FROM bronze.thetadata_ingest_runs r
                    WHERE r.ingest_run_id = EXCLUDED.ingest_run_id)
                > (SELECT started_at FROM bronze.thetadata_ingest_runs r
                    WHERE r.ingest_run_id = silver.option_eod_quotes.ingest_run_id)
              AND (EXCLUDED.bid IS DISTINCT FROM silver.option_eod_quotes.bid
                OR EXCLUDED.ask IS DISTINCT FROM silver.option_eod_quotes.ask
                OR EXCLUDED.mid IS DISTINCT FROM silver.option_eod_quotes.mid
                OR EXCLUDED.bid_size IS DISTINCT FROM silver.option_eod_quotes.bid_size
                OR EXCLUDED.ask_size IS DISTINCT FROM silver.option_eod_quotes.ask_size
                OR EXCLUDED.volume IS DISTINCT FROM silver.option_eod_quotes.volume
                OR EXCLUDED.trade_count IS DISTINCT FROM silver.option_eod_quotes.trade_count
                OR EXCLUDED.underlying_close IS DISTINCT FROM silver.option_eod_quotes.underlying_close)""")
        cur.execute('DROP TABLE qdedup')
        quote_buf.clear()

    for run_id, symbol_, expiry, strike, right_w, trade_date, payload, started in scur:
        pr = per_run[str(run_id)]
        pr['bronze'] += 1
        if pr['bronze'] % 100000 == 0:
            flush_quotes()
            print(f"[quotes] streamed {sum(p['bronze'] for p in per_run.values())} rows...",
                  flush=True)
        data = (payload.get('data') or [])
        if not data:
            pr['bad'] += 1
            continue
        q = data[0]
        # 2026-10-09: skip unencodable strikes — OCC symbology encodes
        # strike*1000 in exactly 8 digits, so strike >= 100000 overflows
        # occ_symbol varchar(21). Seen live: 57 vendor junk rows on SPX
        # 2024-07-09 (strikes 421330.4..1266091.2, decimal-shifted) crashed
        # the contract INSERT with StringDataRightTruncation. Counted as bad
        # so per-run reconciliation still accounts for every bronze row.
        try:
            k1000 = int(round(float(strike) * 1000))
        except (TypeError, ValueError):
            k1000 = -1
        if k1000 < 0 or k1000 > 99999999:
            pr['bad'] += 1
            print(f'[quotes] skip unencodable strike={strike} {symbol_} '
                  f'{trade_date} (counted bad)', flush=True)
            continue
        occ = occ_symbol(symbol_, expiry, strike, right_w)
        contract_id = contract_cache.get(occ)
        if contract_id is None:
            style, settle, mult = UNDERLYING_SPEC.get(symbol_.upper(), DEFAULT_SPEC)
            cur.execute(
                """INSERT INTO silver.option_contracts
                   (occ_symbol, underlying, expiry, strike, option_right, multiplier,
                    exercise_style, settlement, first_seen, last_seen)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (occ_symbol) DO UPDATE
                     SET last_seen = GREATEST(silver.option_contracts.last_seen, EXCLUDED.last_seen),
                         first_seen = LEAST(silver.option_contracts.first_seen, EXCLUDED.first_seen)
                   RETURNING contract_id""",
                (occ, symbol_.upper(), expiry, strike, 'C' if right_w.upper().startswith('C') else 'P',
                 mult, style, settle, trade_date, trade_date))
            contract_id = cur.fetchone()[0]
            contract_cache[occ] = contract_id
            contracts_upserted += 1
        span = contract_span.setdefault(contract_id, [trade_date, trade_date])
        if trade_date < span[0]:
            span[0] = trade_date
        if trade_date > span[1]:
            span[1] = trade_date

        bid, ask = q.get('bid'), q.get('ask')
        mid = None
        if bid is not None and ask is not None and ask > 0 and bid > 0 and bid <= ask:
            mid = (float(bid) + float(ask)) / 2
        flags = quality_flags(bid, ask, q.get('volume'))
        quote_buf.append(
            (contract_id, trade_date, bid, ask, mid, q.get('bid_size'),
             q.get('ask_size'), q.get('volume'), q.get('count'),
             uclose.get((symbol_, trade_date)),
             et_ts(q.get('last_trade')), et_ts(q.get('created')), flags, run_id,
             started))
        if len(quote_buf) >= 5000:
            flush_quotes()
    flush_quotes()

    # greeks invalidation for revised keys (COMPUTED only; VENDOR greeks carry
    # their own revision semantics and are tier-gated off at FREE anyway)
    greeks_invalidated = 0
    if updated_keys:
        cids = [k[0] for k in updated_keys]
        dts = [k[1] for k in updated_keys]
        cur.execute("""
            DELETE FROM silver.option_eod_greeks g
            USING (SELECT * FROM unnest(%s::bigint[], %s::date[])) AS k(cid, td)
            WHERE g.contract_id = k.cid AND g.trade_date = k.td
              AND g.greek_source = 'COMPUTED'""", (cids, dts))
        greeks_invalidated = cur.rowcount
        print(f'[quotes] invalidated {greeks_invalidated} COMPUTED greeks rows '
              f'for {len(updated_keys)} revised quote keys')

    # contract spans
    for cid, (d0, d1) in contract_span.items():
        cur.execute(
            """UPDATE silver.option_contracts
               SET first_seen = LEAST(first_seen, %s),
                   last_seen = GREATEST(last_seen, %s)
               WHERE contract_id = %s""", (d0, d1, cid))

    # per-run reconciliation + ledger
    recon_ok = True
    for rid, started, status in runs:
        p = per_run[str(rid)]
        accounted = p['inserted'] + p['updated'] + p['already_current'] + p['bad']
        ok = (accounted == p['bronze'])
        recon_ok = recon_ok and ok
        cur.execute("""
            INSERT INTO silver.thetadata_load_ledger
                (ingest_run_id, rows_inserted, rows_updated, greeks_invalidated, notes)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ingest_run_id) DO UPDATE SET
                loaded_at = now(), rows_inserted = EXCLUDED.rows_inserted,
                rows_updated = EXCLUDED.rows_updated,
                greeks_invalidated = EXCLUDED.greeks_invalidated,
                notes = EXCLUDED.notes""",
            (rid, p['inserted'], p['updated'],
             greeks_invalidated if len(runs) == 1 else 0,
             f"bronze={p['bronze']} already_current={p['already_current']} "
             f"bad={p['bad']} recon={'OK' if ok else 'MISMATCH'} "
             f"run_status={status} mode={'full' if full else 'incr'}"))
        print(f"[quotes] run {str(rid)[:8]}: bronze={p['bronze']} "
              f"inserted={p['inserted']} updated={p['updated']} "
              f"already_current={p['already_current']} bad={p['bad']} "
              f"recon={'OK' if ok else 'MISMATCH'}")
    conn.commit()
    cur.close()
    return {'runs_processed': len(runs), 'contracts_upserted': contracts_upserted,
            'recon_ok': recon_ok,
            'totals': {k: sum(p[k] for p in per_run.values())
                       for k in ('bronze', 'inserted', 'updated',
                                 'already_current', 'bad')},
            'greeks_invalidated': greeks_invalidated}


def load_greeks(conn, symbol, run_filter, full) -> dict:
    cur = conn.cursor()
    runs = runs_in_scope(cur, symbol, GREEKS_ENDPOINT, run_filter, full)
    if not runs:
        return {'runs_processed': 0}
    run_ids = [r[0] for r in runs]
    cur.execute(
        """SELECT r.ingest_run_id, r.symbol, r.expiration, r.strike, r.option_right,
                  r.trade_date, r.payload, r.request_params
           FROM bronze.thetadata_option_greeks_eod_raw r
           WHERE r.ingest_run_id = ANY(%s::uuid[])""", (run_ids,))
    rows = cur.fetchall()

    inserted = dupes = bad = 0
    for run_id, symbol_, expiry, strike, right_w, trade_date, payload, req_params in rows:
        data = (payload.get('data') or [])
        if not data:
            bad += 1
            continue
        g = data[0]
        occ = occ_symbol(symbol_, expiry, strike, right_w)
        cur.execute('SELECT contract_id FROM silver.option_contracts WHERE occ_symbol=%s', (occ,))
        row = cur.fetchone()
        if not row:
            bad += 1
            continue
        rp = req_params if isinstance(req_params, dict) else json.loads(req_params)
        model_params = {k: rp.get(k) for k in
                        ('rate_type', 'rate_value', 'annual_dividend', 'greeks_version',
                         'underlyer_use_nbbo') if rp.get(k) is not None}
        cur.execute(
            """INSERT INTO silver.option_eod_greeks
               (contract_id, trade_date, implied_vol, delta, gamma, theta, vega, rho,
                iv_error, underlying_price, greek_source, model_params, ingest_run_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'VENDOR',%s,%s)
               ON CONFLICT (contract_id, trade_date, greek_source) DO NOTHING""",
            (row[0], trade_date, g.get('implied_vol'), g.get('delta'), g.get('gamma'),
             g.get('theta'), g.get('vega'), g.get('rho'), g.get('iv_error'),
             g.get('underlying_price'), json.dumps(model_params), run_id))
        if cur.rowcount:
            inserted += 1
        else:
            dupes += 1
    conn.commit()
    cur.close()
    return {'runs_processed': len(runs), 'bronze_rows': len(rows),
            'greeks_inserted': inserted, 'duplicates_rejected': dupes,
            'unparseable': bad}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-id', default=None)
    ap.add_argument('--symbol', default=None)
    ap.add_argument('--full', action='store_true',
                    help='reprocess all runs for the symbol + global recon (weekly job)')
    args = ap.parse_args()

    conn = db.get_connection()
    conn.autocommit = False
    q = load_quotes(conn, args.symbol, args.run_id, args.full)
    g = load_greeks(conn, args.symbol, args.run_id, args.full)

    print('QUOTES:', json.dumps(q))
    print('GREEKS:', json.dumps(g))

    ok = q.get('recon_ok', True)
    if args.full:
        # global reconciliation (weekly): distinct bronze natural keys == silver rows
        cur = conn.cursor()
        sym = args.symbol or 'SPY'
        cur.execute(
            """SELECT count(*) FROM (
                 SELECT DISTINCT symbol, expiration, strike, option_right, trade_date
                 FROM bronze.thetadata_option_eod_raw WHERE symbol = %s
                 AND payload->'data' <> '[]'::jsonb) b""",
            (sym,))
        bronze_distinct = cur.fetchone()[0]
        cur.execute(
            """SELECT count(*) FROM silver.option_eod_quotes qq
               JOIN silver.option_contracts c USING (contract_id)
               WHERE c.underlying = %s""", (sym,))
        silver_total = cur.fetchone()[0]
        conn.close()
        print(f'FULL RECON: bronze distinct natural keys: {bronze_distinct}, '
              f'silver rows: {silver_total}')
        ok = ok and (bronze_distinct == silver_total)
    else:
        conn.close()
    print('RECONCILIATION:', 'OK' if ok else 'MISMATCH')
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
