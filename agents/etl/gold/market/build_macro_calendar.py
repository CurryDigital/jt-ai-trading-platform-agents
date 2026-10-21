#!/usr/bin/env python3
"""
build_macro_calendar.py
=======================
Populates gold.macro_calendar (migration 018) — the global macro catalyst
schedule served by GET /api/macro/calendar (kanban t_7a646947).

Sources (all official published schedules; no fabricated dates):
  LIVE-fetched from this host:
    - FOMC meeting calendar      federalreserve.gov/monetarypolicy/fomccalendars.htm
    - BOJ MPM schedule           boj.or.jp/en/mopo/mpmsche_minu/index.htm
    - HK C&SD press-release XLSX censtatd.gov.hk (annual schedule, CPI + GDP)
  SEEDED (Akamai/JS-blocked from this host; dates verified against the
  official page on 2026-08-12, live fetch still attempted every run):
    - BLS CPI release schedule   bls.gov/schedule/news_release/cpi.htm
    - BLS Employment Situation   bls.gov/schedule/news_release/empsit.htm
    - RBA Board meeting schedule rba.gov.au/schedules-events/board-meeting-schedules.html
    - ECB Governing Council      ecb.europa.eu/press/calendars/mgcgc/html/index.en.html
  RULE:
    - PBoC LPR fixing — published monthly on the 20th (next business day on
      weekends), 09:15 Beijing. Labelled as rule-derived in `source`.

Writes are UPSERT-ONLY (natural key region+event+event_date); rows are never
deleted, so a source outage can never wipe the calendar. A staleness guard
warns when any region's forward coverage drops under 40 days (seeds for
BLS/ECB/RBA/HK run out at end-2026 / end-2027 — refresh the seed then).

Exit code: 0 when >=5 source families produced rows, else 1.
"""

import os
import re
import sys
import zipfile
from datetime import date, timedelta
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed

UA = ('Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) macro-calendar-etl/1.0')

URLS = {
    'fomc': 'https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm',
    'boj': 'https://www.boj.or.jp/en/mopo/mpmsche_minu/index.htm',
    'bls_cpi': 'https://www.bls.gov/schedule/news_release/cpi.htm',
    'bls_nfp': 'https://www.bls.gov/schedule/news_release/empsit.htm',
    'rba': 'https://www.rba.gov.au/schedules-events/board-meeting-schedules.html',
    'ecb': 'https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html',
    'hk_csd_xlsx': 'https://www.censtatd.gov.hk/FileManager/EN/Common/'
                   'Regular_Press_Releases_Schedule_{year}.xlsx',
}

MONTHS = {m.lower(): i for i, m in enumerate(
    ['January', 'February', 'March', 'April', 'May', 'June', 'July',
     'August', 'September', 'October', 'November', 'December'], 1)}
for i, ab in enumerate(['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul',
                        'Aug', 'Sep', 'Sept', 'Oct', 'Nov', 'Dec'], 1):
    MONTHS.setdefault(ab.lower(), i)
MONTHS['sept'] = 9
MONTHS['oct'] = 10
MONTHS['nov'] = 11
MONTHS['dec'] = 12

# --------------------------------------------------------------------------
# SEEDS — verified against the official source pages on 2026-08-12.
# (release_date, reference_month_label) pairs.
# --------------------------------------------------------------------------
BLS_CPI_SEED = [  # https://www.bls.gov/schedule/news_release/cpi.htm
    ('2025-12-18', 'Nov 2025'), ('2026-01-13', 'Dec 2025'),
    ('2026-02-13', 'Jan 2026'), ('2026-03-11', 'Feb 2026'),
    ('2026-04-10', 'Mar 2026'), ('2026-05-12', 'Apr 2026'),
    ('2026-06-10', 'May 2026'), ('2026-07-14', 'Jun 2026'),
    ('2026-08-12', 'Jul 2026'), ('2026-09-11', 'Aug 2026'),
    ('2026-10-14', 'Sep 2026'), ('2026-11-10', 'Oct 2026'),
    ('2026-12-10', 'Nov 2026'),
]
BLS_NFP_SEED = [  # https://www.bls.gov/schedule/news_release/empsit.htm
    ('2025-12-16', 'Nov 2025'), ('2026-01-09', 'Dec 2025'),
    ('2026-02-11', 'Jan 2026'), ('2026-03-06', 'Feb 2026'),
    ('2026-04-03', 'Mar 2026'), ('2026-05-08', 'Apr 2026'),
    ('2026-06-05', 'May 2026'), ('2026-07-02', 'Jun 2026'),
    ('2026-08-07', 'Jul 2026'), ('2026-09-04', 'Aug 2026'),
    ('2026-10-02', 'Sep 2026'), ('2026-11-06', 'Oct 2026'),
    ('2026-12-04', 'Nov 2026'),
]
ECB_SEED = [  # decision day = Day 2 of each monetary policy meeting
    '2026-04-30',  # decision PR ecb.mp260430 (verified via ecb.europa.eu)
    '2026-06-11',  # decision PR ecb.mp260611
    '2026-07-23',  # decision PR ecb.mp260723
    '2026-09-10', '2026-10-29', '2026-12-17',          # ECB GC calendar page
    '2027-02-04', '2027-03-18', '2027-04-29', '2027-06-10',
    '2027-07-22', '2027-09-09', '2027-10-28', '2027-12-16',
]
RBA_SEED = [  # decision day = Day 2 of each Monetary Policy Board meeting
    '2026-02-03', '2026-03-17', '2026-05-05', '2026-06-16',
    '2026-08-11', '2026-09-29', '2026-11-03', '2026-12-08',   # mr-25-02 + board schedule
    '2027-02-09', '2027-03-23', '2027-05-04', '2027-06-22',
    '2027-08-10', '2027-09-28', '2027-11-02', '2027-12-14',   # board schedule page
]


def fetch(url, timeout=30):
    try:
        req = Request(url, headers={'User-Agent': UA, 'Accept': '*/*'})
        with urlopen(req, timeout=timeout) as r:
            data = r.read()
        return data
    except Exception as e:
        print(f'  fetch FAILED {url}: {e}')
        return None


def _ev(region, event, d, importance, source, url):
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return {'region': region, 'event': event, 'event_date': d,
            'importance': importance, 'source': source, 'source_url': url}


# ---------------------------------------------------------------------------
# LIVE parsers
# ---------------------------------------------------------------------------
def parse_fomc(html):
    """Year sections '<a id=N>YYYY FOMC Meetings</a>'; meetings are
    <strong>Month</strong> ... <div fomc-meeting__date>27-28</div>.
    Decision = last day of the range. 'notation vote' entries skipped."""
    out = []
    parts = re.split(r'<a id="\d+">(\d{4}) FOMC Meetings</a>', html)
    today = date.today()
    keep_years = {today.year - 1, today.year, today.year + 1}
    # parts = [head, year1, body1, year2, body2, ...]
    for i in range(1, len(parts) - 1, 2):
        year = int(parts[i])
        if year not in keep_years:
            continue
        body = parts[i + 1]
        for m in re.finditer(
                r'fomc-meeting__month[^>]*><strong>([A-Za-z]+)</strong>.*?'
                r'fomc-meeting__date[^>]*>([^<]+)<', body, re.S):
            mon = MONTHS.get(m.group(1).lower())
            txt = m.group(2).strip()
            if not mon or '(' in txt:          # '(notation vote)' etc.
                continue
            days = re.findall(r'\d+', txt)
            if not days:
                continue
            out.append(_ev('US', 'FOMC Rate Decision',
                           date(year, mon, int(days[-1])), 'High',
                           'FOMC meeting calendar', URLS['fomc']))
    return out


def parse_boj(html):
    """Year sections <h2 id="pYYYY">YYYY</h2> with a table; first <td> of each
    row is the MPM dates: 'Sept. 17 (Thurs.), 18 (Fri.)'. Decision = day 2."""
    out = []
    parts = re.split(r'<h2 id="p(\d{4})">', html)
    today = date.today()
    keep_years = {today.year - 1, today.year, today.year + 1}
    for i in range(1, len(parts) - 1, 2):
        year = int(parts[i])
        if year not in keep_years:
            continue
        body = parts[i + 1].split('<h2', 1)[0]
        for tr in re.findall(r'<tr>(.*?)</tr>', body, re.S):
            tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
            if not tds:
                continue
            txt = re.sub(r'<[^>]+>', ' ', tds[0])
            txt = re.sub(r'\s+', ' ', txt).strip()
            m = re.match(r'([A-Z][a-z]{2,3})\.?\s*(\d{1,2})[^,]*,\s*(\d{1,2})', txt)
            if not m:
                continue
            mon = MONTHS.get(m.group(1).lower())
            if not mon:
                continue
            out.append(_ev('JP', 'BOJ Policy Decision',
                           date(year, mon, int(m.group(3))), 'High',
                           'BOJ MPM schedule', URLS['boj']))
    return out


def _xlsx_rows(data):
    """Minimal stdlib XLSX reader -> list of {colLetter: value}."""
    M = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    z = zipfile.ZipFile(__import__('io').BytesIO(data))
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        for si in root.findall(f'{M}si'):
            shared.append(''.join(t.text or '' for t in si.iter(f'{M}t')))
    rows = []
    for name in sorted(n for n in z.namelist()
                       if re.match(r'xl/worksheets/sheet\d+\.xml', n)):
        root = ET.fromstring(z.read(name))
        for row in root.iter(f'{M}row'):
            cells = {}
            for c in row.findall(f'{M}c'):
                col = re.match(r'[A-Z]+', c.get('r', 'A')).group(0)
                v = c.find(f'{M}v')
                if v is None:
                    cells[col] = ''
                elif c.get('t') == 's':
                    cells[col] = shared[int(v.text)]
                else:
                    cells[col] = v.text
            if any(cells.values()):
                rows.append(cells)
    return rows


def _xldate(v):
    return date(1899, 12, 30) + timedelta(days=int(float(v)))


def parse_hk_csd(xlsx_bytes, url):
    """HK C&SD annual press-release schedule. Keep Consumer Price Index and
    headline Gross Domestic Product series (advance estimates / revised)."""
    out = []
    for r in _xlsx_rows(xlsx_bytes):
        series, title, dval = r.get('D', ''), r.get('E', ''), r.get('A', '')
        try:
            d = _xldate(dval)
        except Exception:
            continue
        if series == 'Consumer Price Index':
            m = re.search(r'for ([A-Z][a-z]+) (\d{4})', title)
            if not m:
                continue
            mon = MONTHS[m.group(1).lower()]
            label = date(2000, mon, 1).strftime('%b')
            out.append(_ev('HK', f'HK CPI ({label} {m.group(2)})', d, 'Med',
                           'HK C&SD press-release schedule', url))
        elif series == 'Gross Domestic Product':
            kind = ('advance estimates' if title.startswith('Advance estimates')
                    else 'revised figures' if title.startswith('Revised figures')
                    else None)
            m = re.search(r'(\d)(?:st|nd|rd|th) Quarter[^\d]*?(\d{4})', title)
            if not kind or not m:
                continue
            imp = 'High' if kind == 'advance estimates' else 'Med'
            out.append(_ev('HK', f'HK GDP Q{m.group(1)} {m.group(2)} ({kind})',
                           d, imp, 'HK C&SD press-release schedule', url))
    return out


# ---------------------------------------------------------------------------
# Best-effort live parses for Akamai/JS-blocked sources (fall back to seed)
# ---------------------------------------------------------------------------
def parse_bls(html, url, event_tpl):
    """BLS schedule table rows: '| July 2026 | Aug. 12, 2026 | 08:30 AM |'."""
    out = []
    text = re.sub(r'<[^>]+>', '|', html)
    for m in re.finditer(
            r'\|\s*([A-Z][a-z]+)\s+(\d{4})\s*\|\s*([A-Z][a-z]+)\.?\s+'
            r'(\d{1,2}),\s*(\d{4})\s*\|', text):
        ref_mon, rel_mon = MONTHS.get(m.group(1).lower()), MONTHS.get(m.group(3).lower())
        if not ref_mon or not rel_mon:
            continue
        label = f'{m.group(1)[:3]} {m.group(2)}'
        out.append(_ev('US', event_tpl.format(label), date(int(m.group(5)), rel_mon, int(m.group(4))),
                       'High', 'BLS release schedule', url))
    return out


def parse_ecb(html):
    out = []
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)
    # Entries look like:
    #   '10/09/2026 Governing Council of the ECB: monetary policy meeting
    #    in Frankfurt (Day 2), followed by press conference'
    # The tempered group must NOT cross into the next dated entry —
    # otherwise a greedy match swallows '(Day 1) DD/MM/YYYY ...' and the
    # captured date belongs to Day 1 while the '(Day 2)' tail is Day 2's.
    for m in re.finditer(
            r'(\d{2})/(\d{2})/(\d{4})\s+Governing Council of the ECB: '
            r'((?:(?!\d{2}/\d{2}/\d{4}).)*?)\(Day 2\)', text):
        if 'monetary policy meeting' not in m.group(4):
            continue
        dd, mm, yyyy = int(m.group(1)), int(m.group(2)), int(m.group(3))
        out.append(_ev('EZ', 'ECB Rate Decision', date(yyyy, mm, dd), 'High',
                       'ECB Governing Council calendar', URLS['ecb']))
    return out


def parse_rba(html):
    out = []
    text = re.sub(r'<[^>]+>', '|', html)
    # 'Board meeting schedules 2026' captions + rows '2–3 February'
    for m in re.finditer(r'Board meeting schedules (\d{4})(.*?)(?:Board meeting schedules \d{4}|$)',
                         text, re.S):
        year, body = int(m.group(1)), m.group(2)
        for mm in re.finditer(r'(\d{1,2})\s*[\u2013-]\s*(\d{1,2})\s+([A-Z][a-z]+)', body):
            mon = MONTHS.get(mm.group(3).lower())
            if mon:
                out.append(_ev('AU', 'RBA Cash Rate Decision',
                               date(year, mon, int(mm.group(2))), 'High',
                               'RBA Board meeting schedule', URLS['rba']))
    return out


def pboc_lpr_events():
    """LPR is fixed on the 20th of each month 09:15 Beijing; weekend -> next
    business day. Rule-labelled so consumers can tell it from scraped dates."""
    out = []
    today = date.today()
    start = (today - timedelta(days=100)).replace(day=1)
    months = []
    y, m = start.year, start.month
    while date(y, m, 1) <= today + timedelta(days=400):
        months.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    for y, m in months:
        d = date(y, m, 20)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        out.append(_ev('CN', 'PBoC LPR Fixing', d, 'Med',
                       'PBoC LPR fixing rule (20th monthly, next business day)',
                       'http://www.chinamoney.com.cn/english/bmklpr/'))
    return out


def seed_events():
    out = []
    for d, ref in BLS_CPI_SEED:
        out.append(_ev('US', f'US CPI ({ref})', d, 'High',
                       'BLS release schedule', URLS['bls_cpi']))
    for d, ref in BLS_NFP_SEED:
        out.append(_ev('US', f'US Payrolls ({ref})', d, 'High',
                       'BLS release schedule', URLS['bls_nfp']))
    for d in ECB_SEED:
        out.append(_ev('EZ', 'ECB Rate Decision', d, 'High',
                       'ECB Governing Council calendar', URLS['ecb']))
    for d in RBA_SEED:
        out.append(_ev('AU', 'RBA Cash Rate Decision', d, 'High',
                       'RBA Board meeting schedule', URLS['rba']))
    return out


# ---------------------------------------------------------------------------
def collect():
    events, ok, failed = [], [], []

    # Live sources
    raw = fetch(URLS['fomc'])
    rows = parse_fomc(raw.decode('utf-8', 'replace')) if raw else []
    (ok if rows else failed).append('fomc')
    events += rows
    print(f'  fomc: {len(rows)} rows (live={bool(raw)})')

    raw = fetch(URLS['boj'])
    rows = parse_boj(raw.decode('utf-8', 'replace')) if raw else []
    (ok if rows else failed).append('boj')
    events += rows
    print(f'  boj: {len(rows)} rows (live={bool(raw)})')

    hk_rows = []
    for yr in (date.today().year, date.today().year + 1):
        url = URLS['hk_csd_xlsx'].format(year=yr)
        raw = fetch(url)
        if raw and raw[:2] == b'PK':
            hk_rows += parse_hk_csd(raw, url)
    (ok if hk_rows else failed).append('hk_csd')
    events += hk_rows
    print(f'  hk_csd: {len(hk_rows)} rows')

    # Best-effort live, seed fallback. A live parse that returns only a
    # handful of rows is more likely a broken parse than a real schedule
    # (BLS ~12/yr, ECB ~8/yr, RBA ~8/yr) — below the floor we discard the
    # live rows and fall back to the verified seed for that family.
    MIN_LIVE = {'bls_cpi': 8, 'bls_nfp': 8, 'ecb': 4, 'rba': 6}
    bls_cpi_rows, bls_nfp_rows, ecb_rows, rba_rows = [], [], [], []
    raw = fetch(URLS['bls_cpi'])
    if raw:
        bls_cpi_rows = parse_bls(raw.decode('utf-8', 'replace'), URLS['bls_cpi'], 'US CPI ({})')
    raw = fetch(URLS['bls_nfp'])
    if raw:
        bls_nfp_rows = parse_bls(raw.decode('utf-8', 'replace'), URLS['bls_nfp'], 'US Payrolls ({})')
    raw = fetch(URLS['ecb'])
    if raw:
        ecb_rows = parse_ecb(raw.decode('utf-8', 'replace'))
    raw = fetch(URLS['rba'])
    if raw:
        rba_rows = parse_rba(raw.decode('utf-8', 'replace'))

    for name, rows in (('bls_cpi', bls_cpi_rows), ('bls_nfp', bls_nfp_rows),
                       ('ecb', ecb_rows), ('rba', rba_rows)):
        if rows and len(rows) < MIN_LIVE[name]:
            print(f'  {name}: live parse yielded only {len(rows)} rows '
                  f'(< {MIN_LIVE[name]} floor) — discarding, using seed')
            rows.clear()

    live_partial = bls_cpi_rows + bls_nfp_rows + ecb_rows + rba_rows
    if live_partial:
        print(f'  live blocked-source parse: bls_cpi={len(bls_cpi_rows)} '
              f'bls_nfp={len(bls_nfp_rows)} ecb={len(ecb_rows)} rba={len(rba_rows)}')
        events += live_partial
        ok += ['bls_cpi', 'bls_nfp', 'ecb', 'rba']
        # Only fall back to seed for families the live parse missed.
        if not bls_cpi_rows:
            events += [e for e in seed_events() if e['event'].startswith('US CPI')]
        if not bls_nfp_rows:
            events += [e for e in seed_events() if e['event'].startswith('US Payrolls')]
        if not ecb_rows:
            events += [e for e in seed_events() if e['region'] == 'EZ']
        if not rba_rows:
            events += [e for e in seed_events() if e['region'] == 'AU']
    else:
        events += seed_events()
        ok += ['bls_seed', 'ecb_seed', 'rba_seed']

    events += pboc_lpr_events()
    ok.append('pboc_rule')

    print(f'sources ok: {ok}; failed: {failed}')
    return events, ok, failed


def upsert(events):
    sql = """
        INSERT INTO gold.macro_calendar
            (region, event, event_date, importance, source, source_url, updated_at)
        VALUES (%(region)s, %(event)s, %(event_date)s, %(importance)s,
                %(source)s, %(source_url)s, NOW())
        ON CONFLICT (region, event, event_date) DO UPDATE SET
            importance = EXCLUDED.importance,
            source     = EXCLUDED.source,
            source_url = EXCLUDED.source_url,
            updated_at = NOW();
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            n = 0
            for e in events:
                cur.execute(sql, e)
                n += 1
            # Forward coverage guard per region
            cur.execute("""
                SELECT region, MIN(event_date), MAX(event_date), COUNT(*)
                FROM gold.macro_calendar GROUP BY region ORDER BY region;
            """)
            cover = cur.fetchall()
        conn.commit()
        return n, cover
    finally:
        conn.close()


def main():
    print('build_macro_calendar: collecting sources...')
    events, ok, failed = collect()
    # Dedupe on natural key (seed vs live may overlap)
    dedup = {(e['region'], e['event'], e['event_date']): e for e in events}
    events = list(dedup.values())
    print(f'total events after dedupe: {len(events)}')

    if len(ok) < 5:
        msg = f'too few sources produced rows: ok={ok} failed={failed}'
        print(f'ERROR: {msg}')
        try:
            conn = get_connection()
            mark_source_refreshed(conn, source='macro_calendar',
                                  asset_class='macro', error=msg)
            conn.close()
        except Exception:
            pass
        return 1

    n, cover = upsert(events)
    print(f'upserted {n} rows into gold.macro_calendar')
    cutoff = date.today() + timedelta(days=40)
    warnings = []
    for region, dmin, dmax, cnt in cover:
        flag = ''
        if dmax < cutoff:
            flag = f'  <-- WARNING: forward coverage ends {dmax} (< {cutoff})'
            warnings.append(region)
        print(f'  {region}: {cnt} rows, {dmin} .. {dmax}{flag}')

    err = ('forward coverage <40d for: ' + ','.join(warnings)) if warnings else None
    try:
        conn = get_connection()
        mark_source_refreshed(conn, source='macro_calendar', asset_class='macro',
                              max_date=max(e['event_date'] for e in events),
                              error=err, expected_frequency='weekly',
                              expected_max_staleness_hours=24 * 9)
        conn.close()
    except Exception as e:
        print(f'  (freshness write skipped: {e})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
