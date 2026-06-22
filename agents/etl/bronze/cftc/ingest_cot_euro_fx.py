#!/usr/bin/env python3
"""
Bronze Ingestion: CFTC Commitment of Traders — EURO FX
Tables:
  silver.cot_euro_fx_daily — weekly COT forward-filled to daily
Source: https://www.cftc.gov/dea/newcot/FinFutWk.txt

Columns extracted (TFF format):
  Col 2  : report_date (YYYY-MM-DD)
  Col 11 : Asset Manager Long
  Col 12 : Asset Manager Short
  Col 14 : Leveraged Funds Long
  Col 15 : Leveraged Funds Short
  Col 17 : Other Reportables Long
  Col 18 : Other Reportables Short

noncomm_long  = Asset Mgr Long + Lev Funds Long + Other Reportables Long
noncomm_short = Asset Mgr Short + Lev Funds Short + Other Reportables Short
net_noncomm   = noncomm_long − noncomm_short
cot_z         = rolling 52-week z-score of net_noncomm

Validation:
  - Raises ValueError if download fails or empty
  - Raises ValueError if EURO FX row not found
  - Raises ValueError if noncomm_long/short negative or NaN
  - Raises ValueError if net_noncomm is zero for >4 consecutive weeks
  - Requires minimum 52 weeks for cot_z computation
"""
import sys, os, csv, io, requests, math
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta
import pandas as pd

COT_URL = 'https://www.cftc.gov/dea/newcot/FinFutWk.txt'
INSTRUMENT = 'EURO FX'
MIN_WEEKS_FOR_Z = 52


def _validate_download(text: str):
    if not text or len(text.strip()) == 0:
        raise ValueError("CFTC download returned empty response")
    if 'EURO FX' not in text:
        raise ValueError("CFTC download missing EURO FX data")


def _validate_positions(noncomm_long: int, noncomm_short: int):
    if noncomm_long < 0 or noncomm_short < 0:
        raise ValueError(f"Negative positions: long={noncomm_long}, short={noncomm_short}")
    if math.isnan(noncomm_long) or math.isnan(noncomm_short):
        raise ValueError(f"NaN positions: long={noncomm_long}, short={noncomm_short}")


def _validate_streak(df: pd.DataFrame):
    """Flag if net_noncomm is zero for >4 consecutive weeks."""
    zero_streak = (df['net_noncomm'] == 0).astype(int)
    max_streak = zero_streak.groupby((zero_streak != zero_streak.shift()).cumsum()).transform('sum').max()
    if max_streak > 4:
        raise ValueError(f"net_noncomm zero for {max_streak} consecutive weeks — data quality issue")


def _validate_zscore(series: pd.Series):
    if series.isna().all():
        raise ValueError("cot_z is all NaN — insufficient history")
    if series.isin([math.inf, -math.inf]).any():
        raise ValueError("cot_z contains Inf values")


def fetch_cot_text() -> str:
    print(f"  Downloading {COT_URL}…")
    resp = requests.get(COT_URL, timeout=60)
    resp.raise_for_status()
    _validate_download(resp.text)
    return resp.text


def parse_euro_fx(text: str) -> dict:
    """Parse the single latest EURO FX row from CFTC TFF text."""
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)

    euro_row = None
    for row in rows:
        if row and row[0].strip().startswith('EURO FX - CHICAGO MERCANTILE EXCHANGE'):
            euro_row = row
            break

    if euro_row is None:
        raise ValueError(f"{INSTRUMENT} row not found in CFTC file")

    report_date = euro_row[2].strip()
    am_long = int(euro_row[11].strip())
    am_short = int(euro_row[12].strip())
    lev_long = int(euro_row[14].strip())
    lev_short = int(euro_row[15].strip())
    other_long = int(euro_row[17].strip())
    other_short = int(euro_row[18].strip())

    noncomm_long = am_long + lev_long + other_long
    noncomm_short = am_short + lev_short + other_short

    _validate_positions(noncomm_long, noncomm_short)

    return {
        'report_date': report_date,
        'noncomm_long': noncomm_long,
        'noncomm_short': noncomm_short,
        'net_noncomm': noncomm_long - noncomm_short,
    }


def build_daily_from_weekly(records: list) -> pd.DataFrame:
    """
    records: list of dicts with report_date, net_noncomm, noncomm_long, noncomm_short
    Returns daily DataFrame with forward-filled values.
    Hard limit: forward-fill max 3 trading days. If gap > 3 days, raise ValueError.
    """
    df = pd.DataFrame(records)
    df['report_date'] = pd.to_datetime(df['report_date']).dt.date
    df = df.sort_values('report_date')

    # Validate streak
    _validate_streak(df)

    # Generate daily calendar
    start_date = df['report_date'].min()
    end_date = date.today()
    daily_dates = pd.date_range(start=start_date, end=end_date, freq='D').date

    daily = pd.DataFrame({'date': daily_dates})
    daily['report_date'] = pd.to_datetime(daily['date']).apply(
        lambda d: df[df['report_date'] <= d.date()]['report_date'].max()
    )

    # Merge weekly data onto daily
    daily = daily.merge(df, on='report_date', how='left', suffixes=('', '_weekly'))

    # Forward fill with 3-day limit
    daily['noncomm_long'] = daily['noncomm_long'].ffill(limit=3)
    daily['noncomm_short'] = daily['noncomm_short'].ffill(limit=3)
    daily['net_noncomm'] = daily['net_noncomm'].ffill(limit=3)

    # Check for gaps > 3 days between consecutive report_dates
    df['prev_date'] = df['report_date'].shift(1)
    df['gap_days'] = (pd.to_datetime(df['report_date']) - pd.to_datetime(df['prev_date'])).dt.days
    max_gap = df['gap_days'].max()
    if max_gap > 7:  # More than 1 week + weekend
        gap_row = df[df['gap_days'] == max_gap].iloc[0]
        print(f"  WARNING: COT gap {gap_row['prev_date']} to {gap_row['report_date']} ({int(max_gap)} days) — will NULL-fill beyond 3-day limit")

    # Check for gaps > 3 days from last report to today
    last_report = df['report_date'].max()
    days_since_last = (pd.to_datetime(date.today()) - pd.to_datetime(last_report)).days
    if days_since_last > 7:
        print(f"  WARNING: COT last report {last_report} is {days_since_last} days old — tail will be NULL")

    # Forward fill with 3-day limit (gaps beyond 3 days stay NULL)
    daily['noncomm_long'] = daily['noncomm_long'].ffill(limit=3)
    daily['noncomm_short'] = daily['noncomm_short'].ffill(limit=3)
    daily['net_noncomm'] = daily['net_noncomm'].ffill(limit=3)

    # Check for any remaining NaNs (should only happen at the tail now)
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

    # Compute 52-week rolling z-score on net_noncomm
    daily['cot_z'] = (
        (daily['net_noncomm'] - daily['net_noncomm'].rolling(window=MIN_WEEKS_FOR_Z * 7, min_periods=MIN_WEEKS_FOR_Z * 7).mean()) /
        daily['net_noncomm'].rolling(window=MIN_WEEKS_FOR_Z * 7, min_periods=MIN_WEEKS_FOR_Z * 7).std()
    )

    _validate_zscore(daily['cot_z'])

    daily['instrument'] = INSTRUMENT
    return daily


def fetch_historical_from_db() -> list:
    """Load previously stored weekly records from DB to build history."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT report_date, noncomm_long, noncomm_short, net_noncomm
        FROM silver.cot_euro_fx_daily
        WHERE instrument = %s
        ORDER BY report_date
    """, (INSTRUMENT,))
    rows = []
    for r in cur.fetchall():
        rows.append({
            'report_date': r[0].isoformat(),
            'noncomm_long': r[1],
            'noncomm_short': r[2],
            'net_noncomm': r[3],
        })
    conn.close()
    return rows


def ingest_cot():
    text = fetch_cot_text()
    latest = parse_euro_fx(text)
    print(f"  Latest COT: {latest['report_date']} net_noncomm={latest['net_noncomm']}")

    # Merge with historical DB records
    historical = fetch_historical_from_db()
    all_records = historical.copy()

    # Avoid duplicate report_date
    existing_dates = {r['report_date'] for r in all_records}
    if latest['report_date'] not in existing_dates:
        all_records.append(latest)

    if len(all_records) < MIN_WEEKS_FOR_Z:
        print(f"⚠️  Only {len(all_records)} weeks available — need {MIN_WEEKS_FOR_Z} for cot_z. Storing raw without z-score.")
        # Store raw weekly record only, no daily expansion yet
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO silver.cot_euro_fx_daily
                (instrument, date, report_date, noncomm_long, noncomm_short, net_noncomm, cot_z, calculated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NULL, NOW())
            ON CONFLICT (instrument, date) DO UPDATE SET
                noncomm_long = EXCLUDED.noncomm_long,
                noncomm_short = EXCLUDED.noncomm_short,
                net_noncomm = EXCLUDED.net_noncomm,
                calculated_at = NOW()
        """, (
            INSTRUMENT,
            latest['report_date'],
            latest['report_date'],
            latest['noncomm_long'],
            latest['noncomm_short'],
            latest['net_noncomm'],
        ))
        conn.commit()
        conn.close()
        print(f"✅ silver.cot_euro_fx_daily — 1 raw row stored (insufficient history for z-score)")
        return

    daily = build_daily_from_weekly(all_records)

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    for _, row in daily.iterrows():
        try:
            cur.execute("""
                INSERT INTO silver.cot_euro_fx_daily
                    (instrument, date, report_date, noncomm_long, noncomm_short, net_noncomm, cot_z, calculated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (instrument, date) DO UPDATE SET
                    report_date = EXCLUDED.report_date,
                    noncomm_long = EXCLUDED.noncomm_long,
                    noncomm_short = EXCLUDED.noncomm_short,
                    net_noncomm = EXCLUDED.net_noncomm,
                    cot_z = EXCLUDED.cot_z,
                    calculated_at = NOW()
            """, (
                row['instrument'],
                row['date'],
                row['report_date'],
                int(row['noncomm_long']),
                int(row['noncomm_short']),
                int(row['net_noncomm']),
                float(row['cot_z']) if pd.notna(row['cot_z']) else None,
            ))
            inserted += 1
        except Exception as e:
            print(f"    Row error {row['date']}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ silver.cot_euro_fx_daily — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_cot()
