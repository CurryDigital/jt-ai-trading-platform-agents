#!/usr/bin/env python3
"""
Macro Event Calendar Ingest — Patch
====================================
Replace FRED-based 1st-of-month placeholder dates with actual
release schedules from Fed, BLS, and EIA.

Export:
    fetch_fomc_dates() -> list[date]
    fetch_bls_dates(report='CPI'|'NFP') -> list[date]
    generate_eia_wednesdays(start, end) -> list[date]
    build_macro_calendar(conn) -> None
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta
import calendar

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None


# ── Hard-coded fallback schedules (2019-2027) ─────────────────────────────────

# FOMC meeting dates (scheduled + unscheduled where known)
# Source: federalreserve.gov/monetarypolicy/fomccalendars.htm
_FOMC_FALLBACK = [
    # 2019
    "2019-01-29", "2019-01-30", "2019-03-19", "2019-03-20", "2019-04-30", "2019-05-01",
    "2019-06-18", "2019-06-19", "2019-07-30", "2019-07-31", "2019-09-17", "2019-09-18",
    "2019-10-29", "2019-10-30", "2019-12-10", "2019-12-11",
    # 2020
    "2020-01-28", "2020-01-29", "2020-03-03", "2020-03-15", "2020-04-29", "2020-06-09",
    "2020-06-10", "2020-07-29", "2020-09-16", "2020-11-04", "2020-11-05", "2020-12-16",
    # 2021
    "2021-01-27", "2021-03-17", "2021-04-28", "2021-06-16", "2021-07-28", "2021-09-22",
    "2021-11-03", "2021-12-15",
    # 2022
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21",
    "2022-11-02", "2022-12-14",
    # 2023
    "2023-01-31", "2023-02-01", "2023-03-21", "2023-03-22", "2023-05-03", "2023-06-14",
    "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    # 2024
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18",
    "2024-11-07", "2024-12-18",
    # 2025
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17",
    "2025-11-06", "2025-12-17",
    # 2026
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-23",
    "2026-11-04", "2026-12-16",
    # 2027
    "2027-01-27", "2027-03-17", "2027-04-28", "2027-06-16", "2027-07-28", "2027-09-22",
    "2027-11-03", "2027-12-15",
]

# CPI release dates (approximate — typically mid-month, second week)
# Source: bls.gov/schedule/news_release/cpi.htm
_CPI_FALLBACK = [
    # 2019
    "2019-01-11", "2019-02-13", "2019-03-12", "2019-04-10", "2019-05-10", "2019-06-12",
    "2019-07-11", "2019-08-13", "2019-09-12", "2019-10-10", "2019-11-13", "2019-12-11",
    # 2020
    "2020-01-14", "2020-02-13", "2020-03-11", "2020-04-10", "2020-05-12", "2020-06-10",
    "2020-07-14", "2020-08-12", "2020-09-11", "2020-10-13", "2020-11-12", "2020-12-10",
    # 2021
    "2021-01-13", "2021-02-10", "2021-03-10", "2021-04-13", "2021-05-12", "2021-06-10",
    "2021-07-13", "2021-08-11", "2021-09-14", "2021-10-13", "2021-11-10", "2021-12-10",
    # 2022
    "2022-01-12", "2022-02-10", "2022-03-10", "2022-04-12", "2022-05-11", "2022-06-10",
    "2022-07-13", "2022-08-10", "2022-09-13", "2022-10-13", "2022-11-10", "2022-12-13",
    # 2023
    "2023-01-12", "2023-02-14", "2023-03-14", "2023-04-12", "2023-05-10", "2023-06-13",
    "2023-07-12", "2023-08-10", "2023-09-13", "2023-10-12", "2023-11-14", "2023-12-12",
    # 2024
    "2024-01-11", "2024-02-13", "2024-03-12", "2024-04-10", "2024-05-15", "2024-06-12",
    "2024-07-11", "2024-08-14", "2024-09-11", "2024-10-10", "2024-11-13", "2024-12-11",
    # 2025
    "2025-01-15", "2025-02-12", "2025-03-12", "2025-04-10", "2025-05-13", "2025-06-11",
    "2025-07-15", "2025-08-12", "2025-09-11", "2025-10-15", "2025-11-12", "2025-12-10",
    # 2026
    "2026-01-14", "2026-02-11", "2026-03-11", "2026-04-14", "2026-05-12", "2026-06-11",
    "2026-07-14", "2026-08-12", "2026-09-10", "2026-10-14", "2026-11-12", "2026-12-10",
    # 2027
    "2027-01-13", "2027-02-10", "2027-03-10", "2027-04-13", "2027-05-12", "2027-06-10",
    "2027-07-13", "2027-08-11", "2027-09-14", "2027-10-13", "2027-11-10", "2027-12-14",
]

# NFP (Employment Situation) release dates (typically first Friday)
# Source: bls.gov/schedule/news_release/empsit.htm
_NFP_FALLBACK = [
    # 2019
    "2019-01-04", "2019-02-01", "2019-03-08", "2019-04-05", "2019-05-03", "2019-06-07",
    "2019-07-05", "2019-08-02", "2019-09-06", "2019-10-04", "2019-11-01", "2019-12-06",
    # 2020
    "2020-01-10", "2020-02-07", "2020-03-06", "2020-04-03", "2020-05-08", "2020-06-05",
    "2020-07-02", "2020-08-07", "2020-09-04", "2020-10-02", "2020-11-06", "2020-12-04",
    # 2021
    "2021-01-08", "2021-02-05", "2021-03-05", "2021-04-02", "2021-05-07", "2021-06-04",
    "2021-07-02", "2021-08-06", "2021-09-03", "2021-10-08", "2021-11-05", "2021-12-03",
    # 2022
    "2022-01-07", "2022-02-04", "2022-03-04", "2022-04-01", "2022-05-06", "2022-06-03",
    "2022-07-08", "2022-08-05", "2022-09-02", "2022-10-07", "2022-11-04", "2022-12-02",
    # 2023
    "2023-01-06", "2023-02-03", "2023-03-10", "2023-04-07", "2023-05-05", "2023-06-02",
    "2023-07-07", "2023-08-04", "2023-09-01", "2023-10-06", "2023-11-03", "2023-12-08",
    # 2024
    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03", "2024-06-07",
    "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04", "2024-11-01", "2024-12-06",
    # 2025
    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02", "2025-06-06",
    "2025-07-03", "2025-08-01", "2025-09-05", "2025-10-03", "2025-11-07", "2025-12-05",
    # 2026
    "2026-01-09", "2026-02-06", "2026-03-06", "2026-04-03", "2026-05-08", "2026-06-05",
    "2026-07-03", "2026-08-07", "2026-09-04", "2026-10-02", "2026-11-06", "2026-12-04",
    # 2027
    "2027-01-08", "2027-02-05", "2027-03-05", "2027-04-02", "2027-05-07", "2027-06-04",
    "2027-07-02", "2027-08-06", "2027-09-03", "2027-10-01", "2027-11-05", "2027-12-03",
]

# US federal holidays (fixed + observed)
_US_HOLIDAYS = set([
    # 2019
    "2019-01-01", "2019-01-21", "2019-02-18", "2019-05-27", "2019-07-04",
    "2019-09-02", "2019-10-14", "2019-11-11", "2019-11-28", "2019-12-25",
    # 2020
    "2020-01-01", "2020-01-20", "2020-02-17", "2020-05-25", "2020-07-03",
    "2020-09-07", "2020-10-12", "2020-11-11", "2020-11-26", "2020-12-25",
    # 2021
    "2021-01-01", "2021-01-18", "2021-02-15", "2021-05-31", "2021-07-05",
    "2021-09-06", "2021-10-11", "2021-11-11", "2021-11-25", "2021-12-24",
    # 2022
    "2022-01-01", "2022-01-17", "2022-02-21", "2022-05-30", "2022-07-04",
    "2022-09-05", "2022-10-10", "2022-11-11", "2022-11-24", "2022-12-26",
    # 2023
    "2023-01-02", "2023-01-16", "2023-02-20", "2023-05-29", "2023-07-04",
    "2023-09-04", "2023-10-09", "2023-11-10", "2023-11-23", "2023-12-25",
    # 2024
    "2024-01-01", "2024-01-15", "2024-02-19", "2024-05-27", "2024-07-04",
    "2024-09-02", "2024-10-14", "2024-11-11", "2024-11-28", "2024-12-25",
    # 2025
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26", "2025-07-04",
    "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27", "2025-12-25",
    # 2026
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-07-03",
    "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-25",
    # 2027
    "2027-01-01", "2027-01-18", "2027-02-15", "2027-05-31", "2027-07-05",
    "2027-09-06", "2027-10-11", "2027-11-11", "2027-11-25", "2027-12-24",
])


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_fomc_dates() -> list:
    """Return list of FOMC meeting dates. Try web scrape first, fallback to hardcoded."""
    dates = _scrape_fomc()
    if not dates:
        print("  Using hardcoded FOMC fallback")
        dates = [date.fromisoformat(d) for d in _FOMC_FALLBACK]
    return sorted(set(dates))


def fetch_bls_dates(report='CPI') -> list:
    """Return list of BLS release dates (CPI or NFP). Fallback to hardcoded."""
    dates = _scrape_bls(report)
    if not dates:
        print(f"  Using hardcoded {report} fallback")
        fallback = _CPI_FALLBACK if report == 'CPI' else _NFP_FALLBACK
        dates = [date.fromisoformat(d) for d in fallback]
    return sorted(set(dates))


def generate_eia_wednesdays(start: date, end: date) -> list:
    """Generate all Wednesdays between start and end, excluding US holidays."""
    result = []
    current = start
    # Find first Wednesday
    while current.weekday() != 2:
        current += timedelta(days=1)
    # Iterate by week
    while current <= end:
        if current.strftime("%Y-%m-%d") not in _US_HOLIDAYS:
            result.append(current)
        current += timedelta(days=7)
    return result


def build_macro_calendar(conn=None):
    """Build silver.macro_event_calendar with actual release dates."""
    if conn is None:
        conn = get_connection()
    cur = conn.cursor()

    today = date.today()
    start = date(2019, 1, 1)

    print("→ Fetching FOMC dates...")
    fomc = fetch_fomc_dates()
    fomc = [d for d in fomc if start <= d <= today]
    print(f"  FOMC dates: {len(fomc)}")

    print("→ Fetching CPI dates...")
    cpi = fetch_bls_dates('CPI')
    cpi = [d for d in cpi if start <= d <= today]
    print(f"  CPI dates: {len(cpi)}")

    print("→ Fetching NFP dates...")
    nfp = fetch_bls_dates('NFP')
    nfp = [d for d in nfp if start <= d <= today]
    print(f"  NFP dates: {len(nfp)}")

    print("→ Generating EIA Wednesdays...")
    eia = generate_eia_wednesdays(start, today)
    print(f"  EIA dates: {len(eia)}")

    # Build unified calendar
    all_dates = {}
    for d in fomc:
        all_dates[d] = {'fomc': 1, 'severity': 3}
    for d in cpi:
        if d not in all_dates:
            all_dates[d] = {'cpi': 1, 'severity': 2}
        else:
            all_dates[d]['cpi'] = 1
            all_dates[d]['severity'] = max(all_dates[d].get('severity', 0), 2)
    for d in nfp:
        if d not in all_dates:
            all_dates[d] = {'nfp': 1, 'severity': 2}
        else:
            all_dates[d]['nfp'] = 1
            all_dates[d]['severity'] = max(all_dates[d].get('severity', 0), 2)
    for d in eia:
        if d not in all_dates:
            all_dates[d] = {'eia': 1, 'severity': 1}
        else:
            all_dates[d]['eia'] = 1
            all_dates[d]['severity'] = max(all_dates[d].get('severity', 0), 1)

    # Ensure table exists
    cur.execute("""
        CREATE TABLE IF NOT EXISTS silver.macro_event_calendar (
            date            DATE PRIMARY KEY,
            cpi_flag        SMALLINT DEFAULT 0,
            nfp_flag        SMALLINT DEFAULT 0,
            fed_funds_flag  SMALLINT DEFAULT 0,
            eia_flag        SMALLINT DEFAULT 0,
            event_flag      SMALLINT DEFAULT 0,
            severity        SMALLINT DEFAULT 0,
            updated_at      TIMESTAMP DEFAULT now()
        )
    """)

    # Clear old data and insert new
    print("  Clearing old macro calendar data...")
    cur.execute("DELETE FROM silver.macro_event_calendar")

    inserted = 0
    for d, flags in sorted(all_dates.items()):
        cur.execute("""
            INSERT INTO silver.macro_event_calendar
                (date, cpi_flag, nfp_flag, fed_funds_flag, eia_flag, event_flag, severity, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
        """, (
            d,
            flags.get('cpi', 0),
            flags.get('nfp', 0),
            flags.get('fomc', 0),
            flags.get('eia', 0),
            1,  # event_flag = 1 for all release dates
            flags.get('severity', 1)
        ))
        inserted += 1

    conn.commit()
    print(f"✅ silver.macro_event_calendar — {inserted} rows inserted")
    conn.close()
    return inserted


# ── Scrapers ──────────────────────────────────────────────────────────────────

def _scrape_fomc() -> list:
    """Try to scrape FOMC dates from federalreserve.gov."""
    if requests is None:
        return []
    try:
        url = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        dates = []
        # Look for panel-pars with date text
        for panel in soup.find_all('div', class_='panel panel-default'):
            for dt in panel.find_all('div', class_='panel-heading'):
                text = dt.get_text(strip=True)
                # Extract "Month DD, YYYY" or "Month DD-DD, YYYY"
                import re
                m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})[-–]?(\d{1,2})?,?\s+(\d{4})', text)
                if m:
                    month_name = m.group(1)
                    day = int(m.group(2))
                    year = int(m.group(4))
                    month_num = list(calendar.month_name).index(month_name)
                    try:
                        dates.append(date(year, month_num, day))
                    except ValueError:
                        pass
        return dates
    except Exception as e:
        print(f"  FOMC scrape failed: {e}")
        return []


def _scrape_bls(report='CPI') -> list:
    """Try to scrape BLS release dates from bls.gov."""
    if requests is None:
        return []
    try:
        if report == 'CPI':
            url = "https://www.bls.gov/schedule/news_release/cpi.htm"
        else:
            url = "https://www.bls.gov/schedule/news_release/empsit.htm"
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        dates = []
        import re
        for td in soup.find_all('td'):
            text = td.get_text(strip=True)
            # Match "Month DD, YYYY" or "Month DD-DD, YYYY"
            m = re.search(r'(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2})[-–]?(\d{1,2})?,?\s+(\d{4})', text)
            if m:
                month_name = m.group(1)
                day = int(m.group(2))
                year = int(m.group(4))
                month_num = list(calendar.month_name).index(month_name)
                try:
                    dates.append(date(year, month_num, day))
                except ValueError:
                    pass
        return dates
    except Exception as e:
        print(f"  BLS {report} scrape failed: {e}")
        return []


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("→ Building macro event calendar...")
    build_macro_calendar()
    print("✅ Macro calendar complete")
