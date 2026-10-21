#!/usr/bin/env python3
"""
Bronze Ingestion: Databento contract-month futures (GLBX.MDP3)
===============================================================
Task: t_822b6365 (Phase A — probe pull only, no subscription).

Tables:
  bronze.databento_futures_contracts — raw landing, PK (root, raw_symbol, date)
  (silver.futures_contract_prices normalization is Phase B — NOT built here)

Source: Databento Historical API, dataset GLBX.MDP3 (CME/CBOT/NYMEX/COMEX).
Schemas: ohlcv-1d (settle via close), definition (expiry/first-notice),
         statistics (open interest).

Modes:
  --probe        Phase A probe: F1-F3 contract months, START_DATE+, full basket.
                 Hard cost gate: estimate via metadata.get_cost, refuse above
                 --max-cost-usd (default 125, signup credit).
  --historical   One-off full history, ALL listed contract months (Phase B
                 sizing tool; still cost-gated).
  --incremental  Daily top-up (last N days). Built for completeness; NOT
                 registered in pipeline_manifest (Phase B decision).
  --estimate-only  Print cost estimate and exit (no data pull).

Credentials: DATABENTO_API_KEY from ~/.hermes/profiles/qr_etl/env/etl.env
             (loaded via dotenv). Never hardcoded.

Cost discipline: NO subscription, NO live feed. All pulls are standard
historical requests billed against credit. Script refuses to exceed budget.
"""
import sys, os, argparse, json
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.expanduser(
    '~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))

ETL_ENV = os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env')

DATASET = 'GLBX.MDP3'
START_DATE = '2010-06-06'
# Full Phase A basket; minimum viable probe = GC (metal) + CL (energy) + ZW (ag)
ALL_ROOTS = ['GC', 'SI', 'HG', 'CL', 'NG', 'ZW', 'ZS', 'ZC']
MIN_ROOTS = ['GC', 'CL', 'ZW']
OPTIONAL_ROOTS = ['HO', 'RB']  # only if estimate is comfortably under budget

MONTH_CODES = {'F': 1, 'G': 2, 'H': 3, 'J': 4, 'K': 5, 'M': 6,
               'N': 7, 'Q': 8, 'U': 9, 'V': 10, 'X': 11, 'Z': 12}


def load_key():
    from dotenv import load_dotenv
    if os.path.exists(ETL_ENV):
        load_dotenv(ETL_ENV, override=True)
    key = os.environ.get('DATABENTO_API_KEY')
    if not key:
        sys.exit(
            "MISSING CREDENTIAL: DATABENTO_API_KEY not found in "
            f"{ETL_ENV} or environment. Add the key from the Databento "
            "portal (signup credit account) and re-run.")
    return key


def get_client():
    import databento as db
    return db.Historical(load_key())


def parse_raw_symbol(sym):
    """'GCZ0' -> (root 'GC', contract_month '2020-12'). Decade ambiguity:
    assume 2010s/2020s based on proximity to today."""
    root = sym[:-2].rstrip('.')
    mc, yr = sym[-2], sym[-1]
    if mc not in MONTH_CODES or not yr.isdigit():
        return None, None
    year = 2020 + int(yr)
    if year > date.today().year + 4:
        year -= 10
    return root, f"{year}-{MONTH_CODES[mc]:02d}"


def estimate_cost_usd(client, roots, start, end, schemas):
    """Sum metadata.get_cost across schemas for parent-symbol pull."""
    total = 0.0
    symbols = [f"{r}.FUT" for r in roots]
    for schema in schemas:
        c = client.metadata.get_cost(dataset=DATASET, symbols=symbols,
                                     schema=schema, start=start, end=end,
                                     stype_in='parent')
        total += float(c)
    return total


def pull_schema(client, roots, start, end, schema, max_months=None):
    """Pull one schema for parent symbols; returns DataFrame with parsed cols."""
    symbols = [f"{r}.FUT" for r in roots]
    data = client.timeseries.get_range(
        dataset=DATASET, symbols=symbols, schema=schema,
        start=start, end=end, stype_in='parent')
    df = data.to_df()
    if df.empty:
        return df
    df = df.reset_index()
    if 'symbol' in df.columns:
        parsed = df['symbol'].map(parse_raw_symbol)
        df['root'] = [p[0] for p in parsed]
        df['contract_month'] = [p[1] for p in parsed]
        df = df.dropna(subset=['root'])
    if max_months is not None and 'contract_month' in df.columns:
        df = filter_front_n(df, max_months)
    return df


def filter_front_n(df, n):
    """Keep only rows whose contract is among the N nearest expiries for that
    (root, date). For ohlcv/statistics frames keyed by trading day."""
    out = []
    key_cols = ['root']
    date_col = 'ts_event' if 'ts_event' in df.columns else 'date'
    day = df[date_col].dt.date if hasattr(df[date_col], 'dt') else df[date_col]
    df = df.assign(_day=day)
    for (root, d), g in df.groupby(['root', '_day']):
        months = sorted(g['contract_month'].unique())[:n]
        out.append(g[g['contract_month'].isin(months)])
    import pandas as pd
    return pd.concat(out).drop(columns=['_day']) if out else df.iloc[0:0]


def upsert_bronze(conn, ohlcv, defs, stats):
    """Merge schemas per (root, raw_symbol, date) and upsert into bronze."""
    import pandas as pd
    o = ohlcv.copy()
    o['date'] = o['ts_event'].dt.date
    o = o.rename(columns={'symbol': 'raw_symbol', 'close': 'settle_close'})
    keep = ['root', 'contract_month', 'raw_symbol', 'date', 'open', 'high',
            'low', 'settle_close', 'volume']
    o = o[[c for c in keep if c in o.columns]]
    o['raw_data'] = o.apply(lambda r: json.dumps({'ohlcv': {
        k: (str(v) if v is not None else None) for k, v in r.items()}}), axis=1)

    if not stats.empty:
        s = stats.copy()
        s['date'] = s['ts_event'].dt.date
        s = s.rename(columns={'symbol': 'raw_symbol'})
        oi = s[s.get('stat_type', 0) == 1][['raw_symbol', 'date', 'quantity']] \
            .rename(columns={'quantity': 'open_interest'}) \
            if 'stat_type' in s.columns else s[['raw_symbol', 'date']]
        if 'open_interest' in oi.columns:
            o = o.merge(oi, on=['raw_symbol', 'date'], how='left')

    if not defs.empty:
        d = defs.copy()
        d = d.rename(columns={'symbol': 'raw_symbol', 'raw_symbol': 'raw_symbol'})
        exp_col = next((c for c in d.columns if 'expiration' in c or 'expiry' in c), None)
        fn_col = next((c for c in d.columns if 'first_notice' in c), None)
        meta = d.groupby('raw_symbol').agg(
            expiry=(exp_col, 'max') if exp_col else ('raw_symbol', 'size'),
            first_notice_date=(fn_col, 'max') if fn_col else ('raw_symbol', 'size')).reset_index()
        o = o.merge(meta, on='raw_symbol', how='left')

    cur = conn.cursor()
    rows = 0
    for _, r in o.iterrows():
        cur.execute("""
            INSERT INTO bronze.databento_futures_contracts
              (root, contract_month, raw_symbol, expiry, first_notice_date,
               date, open, high, low, settle_close, volume, open_interest,
               raw_data)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (root, raw_symbol, date) DO UPDATE SET
              settle_close=EXCLUDED.settle_close, volume=EXCLUDED.volume,
              open_interest=EXCLUDED.open_interest,
              open=EXCLUDED.open, high=EXCLUDED.high, low=EXCLUDED.low,
              expiry=EXCLUDED.expiry, first_notice_date=EXCLUDED.first_notice_date,
              raw_data=EXCLUDED.raw_data, ingested_at=now()
        """, (r.get('root'), r.get('contract_month'), r.get('raw_symbol'),
              r.get('expiry'), r.get('first_notice_date'), r.get('date'),
              r.get('open'), r.get('high'), r.get('low'), r.get('settle_close'),
              r.get('volume'), r.get('open_interest'), r.get('raw_data')))
        rows += 1
        if rows % 5000 == 0:
            conn.commit()
            print(f"  ... {rows} rows upserted")
    conn.commit()
    cur.close()
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', action='store_true')
    ap.add_argument('--historical', action='store_true')
    ap.add_argument('--incremental', action='store_true')
    ap.add_argument('--estimate-only', action='store_true')
    ap.add_argument('--roots', default=','.join(ALL_ROOTS))
    ap.add_argument('--start', default=START_DATE)
    ap.add_argument('--end', default=str(date.today()))
    ap.add_argument('--days', type=int, default=3, help='incremental lookback')
    ap.add_argument('--max-months', type=int, default=None,
                    help='keep only front N contract months (probe=3)')
    ap.add_argument('--max-cost-usd', type=float, default=125.0)
    args = ap.parse_args()

    if not (args.probe or args.historical or args.incremental or args.estimate_only):
        ap.error('choose a mode')

    roots = [r.strip().upper() for r in args.roots.split(',') if r.strip()]
    schemas = ['ohlcv-1d', 'definition', 'statistics']
    max_months = args.max_months or (3 if args.probe else None)
    if args.incremental:
        args.start = str(date.today() - timedelta(days=args.days))

    client = get_client()

    # --- Cost gate (metadata.get_cost is free; never pull blind) ---
    est = estimate_cost_usd(client, roots, args.start, args.end, schemas)
    print(f"COST ESTIMATE: roots={roots} {args.start}..{args.end} "
          f"schemas={schemas} -> ${est:.2f} USD")
    if args.estimate_only:
        return
    if est > args.max_cost_usd:
        if set(roots) != set(MIN_ROOTS):
            est_min = estimate_cost_usd(client, MIN_ROOTS, args.start, args.end, schemas)
            print(f"Over budget. Minimum basket {MIN_ROOTS} -> ${est_min:.2f}")
            if est_min <= args.max_cost_usd:
                sys.exit(f"REFUSED: full basket ${est:.2f} > ${args.max_cost_usd}. "
                         f"Re-run with --roots {','.join(MIN_ROOTS)} (~${est_min:.2f}).")
        sys.exit(f"REFUSED: estimate ${est:.2f} exceeds budget ${args.max_cost_usd}. "
                 "No data pulled. Escalate to user before raising budget.")

    # --- Pull ---
    from db import get_connection
    conn = get_connection()
    total = 0
    frames = {}
    for schema in schemas:
        print(f"Pulling {schema} ...")
        frames[schema] = pull_schema(client, roots, args.start, args.end,
                                     schema, max_months=max_months)
        print(f"  {schema}: {len(frames[schema])} rows")
    total = upsert_bronze(conn, frames['ohlcv-1d'],
                          frames['definition'], frames['statistics'])
    conn.close()
    print(f"DONE: {total} rows upserted into bronze.databento_futures_contracts")


if __name__ == '__main__':
    main()
