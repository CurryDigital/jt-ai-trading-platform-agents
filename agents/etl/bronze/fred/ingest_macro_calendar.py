#!/usr/bin/env python3
"""
Bronze Ingestion: FRED Macro Event Calendar
Table: silver.macro_event_calendar
Source: FRED API (api.stlouisfed.org)

Series:
  CPIAUCSL — Consumer Price Index (All Urban Consumers)
  PAYEMS   — Total Nonfarm Payrolls
  FEDFUNDS — Federal Funds Effective Rate

Logic:
  - Fetch all observations for each series
  - A "release day" is any date where a new observation appears
  - Build daily event_flag: 1 if any series released on that day, else 0

Validation:
  - Raises ValueError if FRED_API_KEY missing
  - Raises ValueError if any series returns <2 observations
  - Raises ValueError if future dates appear (clock skew)
  - Raises ValueError if all flags are 0 for >90 days
"""
import sys, os, requests
from dotenv import load_dotenv
load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'))
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta
import pandas as pd

FRED_API_KEY = os.environ.get('FRED_API_KEY')
FRED_URL = 'https://api.stlouisfed.org/fred/series/observations'

SERIES = {
    'CPIAUCSL': 'cpi_flag',
    'PAYEMS': 'nfp_flag',
    'FEDFUNDS': 'fed_funds_flag',
}


def _validate_api_key():
    if not FRED_API_KEY:
        raise ValueError("FRED_API_KEY not set in environment")


def _validate_series(observations: list, series_id: str):
    if len(observations) < 2:
        raise ValueError(f"FRED series {series_id} returned only {len(observations)} observations — stale/dead")


def _validate_no_future_dates(dates: list):
    today = date.today()
    future = [d for d in dates if d > today]
    if future:
        raise ValueError(f"Future dates detected — clock skew? {future[:5]}")


def _validate_not_all_zero(df: pd.DataFrame):
    """Flag if event_flag is 0 for >90 consecutive days."""
    zero_streak = (df['event_flag'] == 0).astype(int)
    max_streak = zero_streak.groupby((zero_streak != zero_streak.shift()).cumsum()).transform('sum').max()
    if max_streak > 90:
        raise ValueError(f"event_flag is 0 for {max_streak} consecutive days — data quality issue")


def fetch_series(series_id: str) -> list:
    params = {
        'series_id': series_id,
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'sort_order': 'asc',
    }
    resp = requests.get(FRED_URL, params=params, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    observations = data.get('observations', [])
    _validate_series(observations, series_id)
    return observations


def build_calendar() -> pd.DataFrame:
    _validate_api_key()

    release_dates = {flag: set() for flag in SERIES.values()}
    all_dates = set()

    for series_id, flag_col in SERIES.items():
        print(f"→ Fetching {series_id}…")
        observations = fetch_series(series_id)
        for obs in observations:
            val = obs.get('value', '')
            obs_date = obs.get('date')
            if not val or val == '.' or val == '':
                continue
            d = date.fromisoformat(obs_date)
            release_dates[flag_col].add(d)
            all_dates.add(d)

    _validate_no_future_dates(list(all_dates))

    # Build daily calendar from earliest to today
    start_date = min(all_dates)
    end_date = date.today()
    daily_dates = pd.date_range(start=start_date, end=end_date, freq='D').date

    df = pd.DataFrame({'date': daily_dates})
    for flag_col in SERIES.values():
        df[flag_col] = df['date'].apply(lambda d: 1 if d in release_dates[flag_col] else 0)

    df['event_flag'] = (df['cpi_flag'] | df['nfp_flag'] | df['fed_funds_flag']).astype(int)

    _validate_not_all_zero(df)

    return df


def ingest_calendar():
    df = build_calendar()

    conn = get_connection()
    cur = conn.cursor()
    inserted = 0

    for _, row in df.iterrows():
        try:
            cur.execute("""
                INSERT INTO silver.macro_event_calendar
                    (date, cpi_flag, nfp_flag, fed_funds_flag, event_flag, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW())
                ON CONFLICT (date) DO UPDATE SET
                    cpi_flag = EXCLUDED.cpi_flag,
                    nfp_flag = EXCLUDED.nfp_flag,
                    fed_funds_flag = EXCLUDED.fed_funds_flag,
                    event_flag = EXCLUDED.event_flag,
                    updated_at = NOW()
            """, (
                row['date'],
                int(row['cpi_flag']),
                int(row['nfp_flag']),
                int(row['fed_funds_flag']),
                int(row['event_flag']),
            ))
            inserted += 1
        except Exception as e:
            print(f"    Row error {row['date']}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ silver.macro_event_calendar — {inserted} rows upserted")


if __name__ == "__main__":
    ingest_calendar()
