#!/usr/bin/env python3
"""
Bronze Ingestion: CFTC Commitment of Traders — multi-instrument (daily cron)
=============================================================================
Replaces the EURO-FX-only ingest_cot_euro_fx.py (which was never wired into
pipeline_manifest.json and went stale 2026-06-23; kanban t_cf9c5c8b).

Table:
  silver.cot_euro_fx_daily — weekly COT forward-filled to daily, one row per
  calendar day per instrument. (Table name kept for compatibility; it holds
  all four instruments.)

Instruments:
  EURO FX  TFF            EURO FX - CHICAGO MERCANTILE EXCHANGE
  ES       TFF            S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE
  GC       Disaggregated  GOLD - COMMODITY EXCHANGE INC.
  CL       Disaggregated  WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE

Non-commercial construction (matches historical convention):
  TFF:            noncomm = Asset Manager + Leveraged Funds + Other Reportables
  Disaggregated:  noncomm = Managed Money + Other Reportables

Sources:
  Current-year history zips (updated weekly by CFTC):
    https://www.cftc.gov/files/dea/history/fut_fin_txt_YYYY.zip     (TFF)
    https://www.cftc.gov/files/dea/history/fut_disagg_txt_YYYY.zip  (Disaggregated)
  Full backfill (first run for an instrument): 2021 .. current year.

Forward-fill policy (2026-07-30):
  The old script hard-failed when the last report was >3 days old. Production
  data shows unlimited forward-fill (weekly report carried across weekends),
  and a 3-day hard limit guarantees failure every Monday on a Tue-report /
  Mon-Fri-cron schedule. New policy: unlimited ffill, but hard-fail when
    (a) consecutive weekly reports are >21 days apart (real source outage), or
    (b) the latest report is >10 days old (stale feed).
  Z-score: 52-week (364-day) rolling z of net_noncomm, unchanged.
"""
import sys, os, csv, io, math, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date
import requests
import pandas as pd

MIN_WEEKS_FOR_Z = 52
ROLLING_DAYS = MIN_WEEKS_FOR_Z * 7
BACKFILL_START_YEAR = 2021
MAX_REPORT_GAP_DAYS = 21
MAX_STALE_DAYS = 10

INSTRUMENTS = {
    'EURO FX': {
        'report_name': 'EURO FX - CHICAGO MERCANTILE EXCHANGE',
        'source': 'tff',
        'long_cols': [11, 14, 17],    # Asset_Mgr + Lev_Funds + Other_Rept
        'short_cols': [12, 15, 18],
    },
    'ES': {
        'report_name': 'S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE',
        'source': 'tff',
        'long_cols': [11, 14, 17],
        'short_cols': [12, 15, 18],
    },
    'GC': {
        'report_name': 'GOLD - COMMODITY EXCHANGE INC.',
        'source': 'disaggregated',
        'long_cols': [13, 16],        # M_Money + Other_Rept
        'short_cols': [14, 17],
    },
    'CL': {
        'report_name': 'WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE',
        'source': 'disaggregated',
        'long_cols': [13, 16],
        'short_cols': [14, 17],
    },
}

_zip_cache = {}


def fetch_year_zip(year: int, source: str) -> str:
    key = (year, source)
    if key in _zip_cache:
        return _zip_cache[key]
    if source == 'disaggregated':
        url = f'https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip'
    else:
        url = f'https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip'
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    fname = [n for n in z.namelist() if n.endswith('.txt')][0]
    with z.open(fname) as f:
        text = f.read().decode('utf-8')
    _zip_cache[key] = text
    return text


def parse_records(text: str, cfg: dict) -> list:
    reader = csv.reader(io.StringIO(text))
    records = []
    for row in reader:
        if not row or row[0].strip() != cfg['report_name']:
            continue
        try:
            noncomm_long = sum(int(row[c].strip()) for c in cfg['long_cols'])
            noncomm_short = sum(int(row[c].strip()) for c in cfg['short_cols'])
        except (ValueError, IndexError) as e:
            raise ValueError(f"Parse error for {cfg['report_name']} on {row[2]}: {e}")
        if noncomm_long < 0 or noncomm_short < 0:
            raise ValueError(f"Negative positions for {cfg['report_name']} on {row[2]}")
        records.append({
            'report_date': row[2].strip(),
            'noncomm_long': noncomm_long,
            'noncomm_short': noncomm_short,
            'net_noncomm': noncomm_long - noncomm_short,
        })
    return records


def fetch_history_from_db(instrument: str) -> list:
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT report_date, noncomm_long, noncomm_short, net_noncomm
        FROM silver.cot_euro_fx_daily
        WHERE instrument = %s
        ORDER BY report_date
    """, (instrument,))
    rows = [{'report_date': r[0].isoformat(), 'noncomm_long': r[1],
             'noncomm_short': r[2], 'net_noncomm': r[3]} for r in cur.fetchall()]
    conn.close()
    return rows


def fetch_records(instrument: str) -> list:
    """DB history merged with CFTC zips. Full 2021+ backfill when DB history
    is short (<60 weeks); otherwise just the current-year zip."""
    cfg = INSTRUMENTS[instrument]
    db_records = fetch_history_from_db(instrument)
    this_year = date.today().year
    years = list(range(BACKFILL_START_YEAR, this_year + 1)) if len(db_records) < 60 else [this_year]
    all_records = list(db_records)
    for year in years:
        try:
            text = fetch_year_zip(year, cfg['source'])
            recs = parse_records(text, cfg)
            all_records.extend(recs)
            print(f"  {instrument} {year}: {len(recs)} weeks from zip")
        except requests.HTTPError as e:
            print(f"  {instrument} {year}: HTTP {e.response.status_code} — skipping")
    # dedupe by report_date (zip wins over DB on conflict — same values expected)
    deduped = {}
    for r in sorted(all_records, key=lambda x: x['report_date']):
        deduped[r['report_date']] = r
    return [deduped[k] for k in sorted(deduped)]


def build_daily(records: list, instrument: str) -> pd.DataFrame:
    df = pd.DataFrame(records)
    df['report_date'] = pd.to_datetime(df['report_date']).dt.date
    df = df.sort_values('report_date').reset_index(drop=True)

    if len(df) < MIN_WEEKS_FOR_Z:
        raise ValueError(f"{instrument}: only {len(df)} weeks — need {MIN_WEEKS_FOR_Z} for cot_z")

    # Guard: real source outage between consecutive weekly reports
    gaps = df['report_date'].diff().apply(lambda d: d.days if pd.notna(d) else 0)
    max_gap = gaps.max()
    if max_gap > MAX_REPORT_GAP_DAYS:
        i = gaps.idxmax()
        raise ValueError(
            f"{instrument}: COT report gap {df.loc[i-1, 'report_date']} -> "
            f"{df.loc[i, 'report_date']} ({max_gap} days) exceeds {MAX_REPORT_GAP_DAYS}")

    # Guard: stale feed
    last_report = df['report_date'].max()
    days_since = (date.today() - last_report).days
    if days_since > MAX_STALE_DAYS:
        raise ValueError(f"{instrument}: last COT report {last_report} is {days_since} days old — stale feed")

    # Daily calendar, weekly values carried forward (matches production pattern:
    # weekly report held until the next report arrives, weekends included)
    daily_dates = pd.date_range(start=df['report_date'].min(), end=date.today(), freq='D').date
    daily = pd.DataFrame({'date': daily_dates})
    daily['report_date'] = pd.to_datetime(daily['date']).apply(
        lambda d: df[df['report_date'] <= d.date()]['report_date'].max())
    daily = daily.merge(df, on='report_date', how='left')
    daily['noncomm_long'] = daily['noncomm_long'].ffill()
    daily['noncomm_short'] = daily['noncomm_short'].ffill()
    daily['net_noncomm'] = daily['net_noncomm'].ffill()

    if daily['net_noncomm'].isna().any():
        raise ValueError(f"{instrument}: NULL net_noncomm after ffill — corrupt weekly series")

    daily['cot_z'] = (
        (daily['net_noncomm'] - daily['net_noncomm'].rolling(ROLLING_DAYS, min_periods=ROLLING_DAYS).mean()) /
        daily['net_noncomm'].rolling(ROLLING_DAYS, min_periods=ROLLING_DAYS).std()
    )
    if daily['cot_z'].isna().all():
        raise ValueError(f"{instrument}: cot_z all NaN — insufficient history")
    if daily['cot_z'].isin([math.inf, -math.inf]).any():
        raise ValueError(f"{instrument}: cot_z contains Inf")

    daily['instrument'] = instrument
    return daily


def upsert_daily(daily: pd.DataFrame, instrument: str) -> int:
    conn = get_connection()
    cur = conn.cursor()
    from psycopg2.extras import execute_values
    rows = [(
        instrument,
        row['date'],
        row['report_date'],
        int(row['noncomm_long']),
        int(row['noncomm_short']),
        int(row['net_noncomm']),
        float(row['cot_z']) if pd.notna(row['cot_z']) else None,
    ) for _, row in daily.iterrows()]
    execute_values(cur, """
        INSERT INTO silver.cot_euro_fx_daily
            (instrument, date, report_date, noncomm_long, noncomm_short, net_noncomm, cot_z, calculated_at)
        VALUES %s
        ON CONFLICT (instrument, date) DO UPDATE SET
            report_date = EXCLUDED.report_date,
            noncomm_long = EXCLUDED.noncomm_long,
            noncomm_short = EXCLUDED.noncomm_short,
            net_noncomm = EXCLUDED.net_noncomm,
            cot_z = EXCLUDED.cot_z,
            calculated_at = NOW()
    """, rows, template="(%s, %s, %s, %s, %s, %s, %s, NOW())", page_size=1000)
    conn.commit()
    conn.close()
    return len(rows)


def _mark_freshness(error=None):
    try:
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='cftc', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


def main():
    total = 0
    for instrument in INSTRUMENTS:
        print(f"▶ {instrument}")
        records = fetch_records(instrument)
        print(f"  {len(records)} unique weekly reports "
              f"({records[0]['report_date']} .. {records[-1]['report_date']})")
        daily = build_daily(records, instrument)
        n = upsert_daily(daily, instrument)
        total += n
        print(f"✅ silver.cot_euro_fx_daily — {n} rows upserted for {instrument}")
    print(f"Done. {total} total rows across {len(INSTRUMENTS)} instruments.")


if __name__ == '__main__':
    try:
        main()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
