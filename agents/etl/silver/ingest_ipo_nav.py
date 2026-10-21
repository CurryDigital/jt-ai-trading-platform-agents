#!/usr/bin/env python3
"""
Silver: ingest offer-price-to-NAV for HK IPOs (kanban t_ef6032f4, 2026-09-23)
=============================================================================
Purpose: populate silver.unified_ipo_calendar.nav_per_share_hkd / nav_asof /
nav_source so the backend can serve offer_to_nav_pct on
/api/hkex/ipos[/subscription] — lets subscribers skip IPOs priced at/above NAV.

Source: HKEX prospectus PDF, appendix table "Unaudited pro forma adjusted
consolidated net tangible assets ... per Share". Each scenario row looks like:
    Based on an Offer Price of HK$41.50 per Share ... 3,579,722 2,338,954 \
        5,918,676 8.71 10.08
trailing columns are (RMB'000 aggregates..., RMB per share, HK$ per share);
the LAST number is the HK$ per-share NAV we store.

Scenario selection: fixed-price prospectuses have one row; ranged deals have
one row per scenario — pick the row closest to (offer_price_low+high)/2 so
nav_per_share_hkd matches the offer_to_nav_pct basis used by the backend.

Target rows (default): silver.unified_ipo_calendar rows with nav_per_share_hkd
IS NULL and (application_end >= today OR listing_date >= today - 14d OR
listing_date IS NULL with application window columns present). Use
--tickers 9607.HK,... to force specific tickers, --dry-run to print only.

Idempotent: skips rows that already have nav_per_share_hkd unless --force.
Extraction verified 2026-09-23 against 9607/6731/3757/3228/6802.HK prospectuses.
"""
import argparse
import gc
import io
import os
import re
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection  # noqa: E402

try:
    import requests
    import pdfplumber
    import ipo_price_range_core as core
except ImportError as e:
    print(f'missing package: {e.name}')
    sys.exit(2)

NUM = r'\(?[\d,]+(?:\.\d+)?\)?'
# Tolerates merged words ("Basedonan OfferPriceof HK$21.60perHShare",
# "BasedontheOfferPriceof HK$436.0perHShare") and pdfplumber (cid:N) bullet
# garbage between "per Share" and the numbers (the cid digits broke the old
# tempered-dot gap). The numeric window is captured raw and (cid:N) tokens are
# stripped before NUM extraction.
ROW_PAT = re.compile(
    r'Based\s*on\s*(?:an?|the)\s*(?:minimum\s*|maximum\s*)?Offer\s*Price\s*of\s*HK\$\s*'
    r'([\d.,]+)\s*per\s*(?:[A-Za-z]+\s*){0,3}Share'
    r'((?:(?!Based\s*on\s*(?:an?|the)\s*(?:minimum\s*|maximum\s*)?Offer\s*Price\s*of\s*HK\$).){0,220})',
    re.I | re.S)
ASOF_PAT = re.compile(
    r'as\s*at\s*(?:the\s*)?(\d{1,2}\s*[A-Za-z]+\s*\d{4}|[A-Za-z]+\s*\d{1,2},?\s*\d{4})',
    re.I)


def parse_num(x):
    neg = x.startswith('(')
    v = float(x.strip('()').replace(',', ''))
    return -v if neg else v


def parse_asof(text):
    m = ASOF_PAT.search(text.replace('\n', ' '))
    if not m:
        return None
    s = re.sub(r'\s+', ' ', m.group(1)).replace(',', '')
    s = re.sub(r'(\d)([A-Za-z])', r'\1 \2', s)  # merged "30April" -> "30 April"
    s = re.sub(r'([A-Za-z])(\d)', r'\1 \2', s)  # merged "April2026" -> "April 2026"
    for fmt in ('%d %B %Y', '%B %d %Y'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def extract_nav_rows(content, scan_back=350):
    """Return [(offer_price, nav_hkd, asof, page)] from a prospectus PDF."""
    found = []
    with pdfplumber.open(io.BytesIO(content)) as doc:
        n = len(doc.pages)
        for i in range(n - 1, max(n - scan_back, -1), -1):
            page = doc.pages[i]
            t = page.extract_text() or ''
            page.flush_cache()  # OOM guard: drop pdfminer char cache per page
            fl = t.lower().replace(' ', '').replace('\n', '')
            if 'nettangibleassets' not in fl or 'pershare' not in fl:
                continue
            flat = re.sub(r'\s+', ' ', t)
            asof = parse_asof(t)
            for m in ROW_PAT.finditer(flat):
                offer = float(m.group(1).replace(',', ''))
                seg = re.sub(r'\(cid:\d+\)', ' ', m.group(2))
                # cut page-footers ('– II-1 –') and trailing notes so their
                # digits cannot poison the last-column NAV
                seg = re.split(r'\s[–—]\s|\bNotes?\s*[:：]', seg)[0]
                vals = [parse_num(x) for x in re.findall(NUM, seg)
                        if re.search(r'\d', x)][:8]
                if len(vals) < 2:
                    # a genuine NTA row carries aggregates + per-share columns;
                    # a lone number is prose (e.g. 'representing 4.3% of ...')
                    continue
                nav = vals[-1]  # last column = HK$ per share
                if nav <= 0 or nav >= offer:
                    continue  # sanity: NAV must be positive and below offer
                found.append((offer, nav, asof, i))
    return found


def pick_scenario(rows, fixed_price, low, high):
    if not rows:
        return None
    # Prefer the mid-range scenario whenever a range exists — rows with
    # fixed_price=True can still carry low/high (e.g. 9607.HK: fixed=True,
    # low=39.0, high=44.0) and the backend's offer_to_nav_pct basis
    # (top-of-range) matches the mid-row NAV convention.
    if low is None or high is None or len(rows) == 1:
        return rows[0]
    mid = (float(low) + float(high)) / 2.0
    return min(rows, key=lambda r: abs(r[0] - mid))


def target_tickers(conn):
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DISTINCT ticker FROM silver.unified_ipo_calendar
            WHERE nav_per_share_hkd IS NULL
              AND (application_end >= CURRENT_DATE
                   OR listing_date >= CURRENT_DATE - INTERVAL '14 days'
                   OR (listing_date IS NULL AND application_start IS NOT NULL))
            ORDER BY ticker
        """)
        return [r[0] for r in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--tickers', help='comma list, e.g. 9607.HK,6802.HK')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true',
                    help='re-extract even when nav_per_share_hkd is set')
    args = ap.parse_args()

    sess = requests.Session()
    sess.headers.update({'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36'})

    conn = get_connection()
    if args.tickers:
        tickers = [t.strip() for t in args.tickers.split(',') if t.strip()]
        if not args.force:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT ticker FROM silver.unified_ipo_calendar
                    WHERE ticker = ANY(%s) AND nav_per_share_hkd IS NOT NULL
                """, (tickers,))
                done = {r[0] for r in cur.fetchall()}
            tickers = [t for t in tickers if t not in done]
    else:
        tickers = target_tickers(conn)
        if args.force:
            pass  # target list already filters to NULL nav; --force only affects --tickers

    print(f'targets: {len(tickers)}')
    n_ok = n_skip = n_err = 0
    for ticker in tickers:
        code = ticker.split('.')[0].zfill(5)
        t0 = time.time()
        try:
            sid = core.get_stock_id(sess, code)
            docs = core.search_docs(sess, sid, '20260501', '20261231')
            cands = core.pick_prospectus(docs)
            if not cands:
                print(f'{ticker}: SKIP no prospectus found')
                n_skip += 1
                continue
            url = core.HOST + cands[0]['FILE_LINK']
            content = sess.get(url, timeout=180).content
            content_kb = len(content) // 1024
            rows = extract_nav_rows(content)
            del content  # OOM guard: free PDF bytes before further work
            gc.collect()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT fixed_price, offer_price_low, offer_price_high
                    FROM silver.unified_ipo_calendar WHERE ticker = %s
                    ORDER BY listing_date DESC NULLS LAST LIMIT 1
                """, (ticker,))
                meta = cur.fetchone()
            fixed, low, high = meta if meta else (None, None, None)
            pick = pick_scenario(rows, fixed, low, high)
            if pick is None:
                print(f'{ticker}: SKIP no NTA-per-share row ({content_kb}KB scanned)')
                n_skip += 1
                continue
            offer, nav, asof, page = pick
            source = f'prospectus {url} p.{page + 1} (offer HK${offer})'
            print(f'{ticker}: nav_hkd={nav} asof={asof} @offer={offer} '
                  f'({len(rows)} scenarios, {time.time() - t0:.0f}s)')
            if not args.dry_run:
                with conn.cursor() as cur:
                    cur.execute("""
                        UPDATE silver.unified_ipo_calendar s
                        SET nav_per_share_hkd = %s, nav_asof = %s, nav_source = %s,
                            updated_at = NOW()
                        WHERE s.id = (
                            SELECT id FROM silver.unified_ipo_calendar
                            WHERE ticker = %s
                            ORDER BY listing_date DESC NULLS LAST LIMIT 1)
                    """, (nav, asof, source, ticker))
                conn.commit()
            n_ok += 1
        except Exception as e:
            conn.rollback()
            print(f'{ticker}: ERROR {type(e).__name__} {e}')
            n_err += 1
            if n_err > 5:
                print('too many errors, aborting')
                sys.exit(1)
    conn.close()
    print(f'done: ok={n_ok} skip={n_skip} err={n_err}')
    sys.exit(0 if n_err == 0 else 1)


if __name__ == '__main__':
    main()
