#!/usr/bin/env python3
"""
Bronze→Gold Ingestion: CFTC Commitment of Traders — GC / CL / ES Expansion

Tables:
  gold.cot_sentiment — appends GC, CL, ES using existing EURO FX schema

Source:
  CFTC Disaggregated Futures (GC, CL):  https://www.cftc.gov/files/dea/history/fut_disagg_txt_YYYY.zip
  CFTC TFF Futures       (ES):         https://www.cftc.gov/files/dea/history/fut_fin_txt_YYYY.zip

Ticker mapping:
  GC  →  GOLD - COMMODITY EXCHANGE INC.                    (Disaggregated)
  CL  →  WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE       (Disaggregated)
  ES  →  S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE (TFF)

Non-commercial construction (matches EURO FX methodology):
  Disaggregated:  noncomm = Managed Money + Other Reportables
  TFF:            noncomm = Asset Manager + Leveraged Funds + Other Reportables

Z-score:
  52-week (364-day) rolling z-score on net_noncomm, identical to EURO FX.

Daily expansion:
  Weekly COT values forward-filled to daily calendar (same as EURO FX).
  Hard limit: 3-day forward fill. Gaps > 3 days stay NULL (raises if gap
  exceeds 3 days between valid weeks, same validation as EURO FX ingest).

Data quality note:
  COT has duplicate report_date rows because weekly data is forward-filled
  to daily.  This script inserts daily-forward-filled rows (one per calendar
  day) to match the existing EURO FX pattern in gold.cot_sentiment.

Historical backfill:
  Downloads all available yearly zip files from 2021 through current year.
  Deduplicates by (instrument, report_date) before daily expansion.
"""
import sys, os, csv, io, requests, math, zipfile
from datetime import date, timedelta
from typing import List, Dict

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

import pandas as pd

# ── Config ───────────────────────────────────────────────────────────────────
MIN_WEEKS_FOR_Z = 52
ROLLING_DAYS = MIN_WEEKS_FOR_Z * 7          # 364-day rolling window

TICKERS = {
    'GC': {
        'report_name': 'GOLD - COMMODITY EXCHANGE INC.',
        'source': 'disaggregated',
        'long_cols':  [13, 16],   # M_Money_Long + Other_Rept_Long
        'short_cols': [14, 17],   # M_Money_Short + Other_Rept_Short
    },
    'CL': {
        'report_name': 'WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE',
        'source': 'disaggregated',
        'long_cols':  [13, 16],
        'short_cols': [14, 17],
    },
    'ES': {
        'report_name': 'S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE',
        'source': 'tff',
        'long_cols':  [11, 14, 17],   # Asset_Mgr + Lev_Money + Other_Rept
        'short_cols': [12, 15, 18],
    },
}

YEARS = list(range(2021, date.today().year + 1))

# ── Validation helpers (mirror EURO FX ingest) ───────────────────────────────
def _validate_positions(noncomm_long: int, noncomm_short: int):
    if noncomm_long < 0 or noncomm_short < 0:
        raise ValueError(f"Negative positions: long={noncomm_long}, short={noncomm_short}")
    if math.isnan(noncomm_long) or math.isnan(noncomm_short):
        raise ValueError(f"NaN positions: long={noncomm_long}, short={noncomm_short}")


def _validate_streak(df: pd.DataFrame):
    zero_streak = (df['net_noncomm'] == 0).astype(int)
    max_streak = zero_streak.groupby((zero_streak != zero_streak.shift()).cumsum()).transform('sum').max()
    if max_streak > 4:
        raise ValueError(f"net_noncomm zero for {max_streak} consecutive weeks — data quality issue")


def _validate_zscore(series: pd.Series):
    if series.isna().all():
        raise ValueError("cot_z is all NaN — insufficient history")
    if series.isin([math.inf, -math.inf]).any():
        raise ValueError("cot_z contains Inf values")


# ── Fetch ────────────────────────────────────────────────────────────────────
def fetch_year_zip(year: int, source: str) -> str:
    """Download CFTC zip for a given year and source, return decoded text."""
    if source == 'disaggregated':
        url = f'https://www.cftc.gov/files/dea/history/fut_disagg_txt_{year}.zip'
    else:
        url = f'https://www.cftc.gov/files/dea/history/fut_fin_txt_{year}.zip'
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(resp.content))
    fname = [n for n in z.namelist() if n.endswith('.txt')][0]
    with z.open(fname) as f:
        return f.read().decode('utf-8')


def parse_ticker_rows(text: str, report_name: str, long_cols: List[int], short_cols: List[int]) -> List[Dict]:
    """Parse all rows matching report_name from CFTC text file."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    records = []
    for row in rows:
        if not row or row[0].strip() != report_name:
            continue
        report_date = row[2].strip()
        try:
            noncomm_long = sum(int(row[c].strip()) for c in long_cols)
            noncomm_short = sum(int(row[c].strip()) for c in short_cols)
        except (ValueError, IndexError) as e:
            raise ValueError(f"Parse error for {report_name} on {report_date}: {e}")
        _validate_positions(noncomm_long, noncomm_short)
        records.append({
            'report_date': report_date,
            'noncomm_long': noncomm_long,
            'noncomm_short': noncomm_short,
            'net_noncomm': noncomm_long - noncomm_short,
        })
    return records


def fetch_all_history(ticker: str) -> List[Dict]:
    """Download and parse all historical weekly records for a ticker."""
    cfg = TICKERS[ticker]
    all_records = []
    for year in YEARS:
        try:
            text = fetch_year_zip(year, cfg['source'])
            records = parse_ticker_rows(text, cfg['report_name'], cfg['long_cols'], cfg['short_cols'])
            all_records.extend(records)
            print(f"  {ticker} {year}: {len(records)} weeks")
        except requests.HTTPError as e:
            print(f"  {ticker} {year}: HTTP error {e.response.status_code} — skipping")
    # Deduplicate by report_date
    seen = set()
    deduped = []
    for r in sorted(all_records, key=lambda x: x['report_date']):
        if r['report_date'] not in seen:
            seen.add(r['report_date'])
            deduped.append(r)
    return deduped


# ── Transform ────────────────────────────────────────────────────────────────
def build_daily_from_weekly(records: List[Dict], instrument: str) -> pd.DataFrame:
    """
    Weekly COT records → daily DataFrame with forward-fill and 52-week z-score.
    Mirrors build_daily_from_weekly() in ingest_cot_euro_fx.py exactly.
    """
    df = pd.DataFrame(records)
    df['report_date'] = pd.to_datetime(df['report_date']).dt.date
    df = df.sort_values('report_date')

    _validate_streak(df)

    start_date = df['report_date'].min()
    end_date = date.today()
    daily_dates = pd.date_range(start=start_date, end=end_date, freq='D').date

    daily = pd.DataFrame({'date': daily_dates})
    daily['report_date'] = pd.to_datetime(daily['date']).apply(
        lambda d: df[df['report_date'] <= d.date()]['report_date'].max()
    )

    daily = daily.merge(df, on='report_date', how='left', suffixes=('', '_weekly'))

    # Forward fill with 3-day limit
    daily['noncomm_long'] = daily['noncomm_long'].ffill(limit=3)
    daily['noncomm_short'] = daily['noncomm_short'].ffill(limit=3)
    daily['net_noncomm'] = daily['net_noncomm'].ffill(limit=3)

    # Gap warnings
    df['prev_date'] = df['report_date'].shift(1)
    df['gap_days'] = (pd.to_datetime(df['report_date']) - pd.to_datetime(df['prev_date'])).dt.days
    max_gap = df['gap_days'].max()
    if max_gap > 7:
        gap_row = df[df['gap_days'] == max_gap].iloc[0]
        print(f"  WARNING: COT gap {gap_row['prev_date']} to {gap_row['report_date']} ({int(max_gap)} days)")

    last_report = df['report_date'].max()
    days_since_last = (pd.to_datetime(date.today()) - pd.to_datetime(last_report)).days
    if days_since_last > 7:
        print(f"  WARNING: COT last report {last_report} is {days_since_last} days old — tail will be NULL")

    # Re-apply ffill limit (mirrors original script)
    daily['noncomm_long'] = daily['noncomm_long'].ffill(limit=3)
    daily['noncomm_short'] = daily['noncomm_short'].ffill(limit=3)
    daily['net_noncomm'] = daily['net_noncomm'].ffill(limit=3)

    # Check for remaining NaNs
    null_mask = daily['net_noncomm'].isna()
    if null_mask.any():
        first_null_idx = null_mask.idxmax()
        first_null_date = daily.loc[first_null_idx, 'date']
        last_valid_idx = first_null_idx - 1
        last_valid_date = daily.loc[last_valid_idx, 'date'] if last_valid_idx >= 0 else None
        raise ValueError(
            f"COT forward-fill gap exceeds 3 trading days: "
            f"last valid {last_valid_date} to first null {first_null_date}"
        )

    # 52-week rolling z-score
    daily['cot_z'] = (
        (daily['net_noncomm'] - daily['net_noncomm'].rolling(window=ROLLING_DAYS, min_periods=ROLLING_DAYS).mean()) /
        daily['net_noncomm'].rolling(window=ROLLING_DAYS, min_periods=ROLLING_DAYS).std()
    )

    _validate_zscore(daily['cot_z'])

    daily['instrument'] = instrument
    return daily


def assign_sentiment(cot_z: float) -> str:
    """Sentiment buckets matching EURO FX convention."""
    if pd.isna(cot_z):
        return 'neutral'
    if cot_z > 1.0:
        return 'bearish'
    if cot_z < -1.0:
        return 'bullish'
    return 'neutral'


# ── Load ─────────────────────────────────────────────────────────────────────
def load_to_gold(daily: pd.DataFrame, ticker: str) -> int:
    """Upsert daily rows into gold.cot_sentiment. Returns row count."""
    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    for _, row in daily.iterrows():
        sentiment = assign_sentiment(row['cot_z'])
        signal_flag = 1 if sentiment != 'neutral' else 0
        try:
            cur.execute("""
                INSERT INTO gold.cot_sentiment
                    (instrument, date, report_date, noncomm_long, noncomm_short,
                     net_noncomm, cot_z, sentiment, signal_flag, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (instrument, date) DO UPDATE SET
                    report_date = EXCLUDED.report_date,
                    noncomm_long = EXCLUDED.noncomm_long,
                    noncomm_short = EXCLUDED.noncomm_short,
                    net_noncomm = EXCLUDED.net_noncomm,
                    cot_z = EXCLUDED.cot_z,
                    sentiment = EXCLUDED.sentiment,
                    signal_flag = EXCLUDED.signal_flag,
                    updated_at = NOW()
            """, (
                ticker,
                row['date'],
                row['report_date'],
                int(row['noncomm_long']),
                int(row['noncomm_short']),
                int(row['net_noncomm']),
                float(row['cot_z']) if pd.notna(row['cot_z']) else None,
                sentiment,
                signal_flag,
            ))
            inserted += 1
        except Exception as e:
            print(f"    Row error {row['date']}: {e}")

    conn.commit()
    conn.close()
    return inserted


# ── Main ─────────────────────────────────────────────────────────────────────
def ingest_ticker(ticker: str):
    print(f"\n▶ {ticker}")
    records = fetch_all_history(ticker)
    print(f"  Total unique weeks: {len(records)}")

    if len(records) < MIN_WEEKS_FOR_Z:
        print(f"⚠️  Only {len(records)} weeks available — need {MIN_WEEKS_FOR_Z} for cot_z. Storing raw without z-score.")
        conn = get_connection()
        cur = conn.cursor()
        for r in records:
            cur.execute("""
                INSERT INTO gold.cot_sentiment
                    (instrument, date, report_date, noncomm_long, noncomm_short,
                     net_noncomm, cot_z, sentiment, signal_flag, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, NULL, 'neutral', 0, NOW())
                ON CONFLICT (instrument, date) DO UPDATE SET
                    noncomm_long = EXCLUDED.noncomm_long,
                    noncomm_short = EXCLUDED.noncomm_short,
                    net_noncomm = EXCLUDED.net_noncomm,
                    updated_at = NOW()
            """, (ticker, r['report_date'], r['report_date'],
                  r['noncomm_long'], r['noncomm_short'], r['net_noncomm']))
        conn.commit()
        conn.close()
        print(f"✅ gold.cot_sentiment — {len(records)} raw rows stored (insufficient history for z-score)")
        return

    daily = build_daily_from_weekly(records, ticker)
    inserted = load_to_gold(daily, ticker)
    print(f"✅ gold.cot_sentiment — {inserted} rows upserted for {ticker}")


def main():
    print("COT Coverage Expansion: GC / CL / ES")
    for ticker in ['GC', 'CL', 'ES']:
        ingest_ticker(ticker)
    print("\nDone.")


if __name__ == "__main__":
    main()
