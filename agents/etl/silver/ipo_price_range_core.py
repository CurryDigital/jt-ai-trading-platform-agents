#!/usr/bin/env python3
"""
backfill_ipo_price_range.py — HK IPO indicative offer price range extractor.

Source: HKEXnews listing documents (prospectus / GEM listing doc), which state
"The Offer Price will not be more than HK$X ... not less than HK$Y" (ranged) or a
single fixed price. Allotment announcements do NOT restate the range (verified
2026-08-31), and AAStocks/etnet/NLR lack historical ranges — prospectus is the
only free authoritative source.

Writes:
  bronze.hkex_ipo_price_range_raw  (audit, one row per attempted IPO, resumable)
  silver.unified_ipo_calendar      (offer_price_low/high, price_range_source, fixed_price)

Idempotent: skips tickers already present in bronze with status 'ok'/'fixed'.
"""
import os, re, io, sys, json, time, argparse
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'shared', 'scripts'))
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
from db import get_connection  # noqa: E402

HEADERS = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36',
           'Referer': 'https://www1.hkexnews.hk/search/titlesearch.xhtml?lang=en'}
HOST = 'https://www1.hkexnews.hk'

PROSP_TITLE = re.compile(
    r'GLOBAL OFFERING|LISTING DOCUMENT|PROSPECTUS|'
    r'LISTING ON THE GROWTH ENTERPRISE MARKET|PLACING|SHARE OFFER', re.I)
# titles to exclude even if they match above
EXCLUDE_TITLE = re.compile(r'PHIP|APPLICATION PROOF|POST HEARING', re.I)

# space-tolerant because pdfplumber often merges words on cover pages; re.I for "Not more than"
RANGE_PATS = [
    # "not more than HK$22.00 ... not less than HK$17.00" -> (high, low)
    (re.compile(r'not\s*(?:be\s*)?more\s*than\s*HK\$\s*([\d.,]+?)\s*per.{0,400}?not\s*(?:be\s*)?less\s*than\s*HK\$\s*([\d.,]+)', re.S | re.I), 'hl'),
    (re.compile(r'not\s*(?:be\s*)?more\s*than\s*HK\$\s*([\d.,]+)[^%]{0,400}?not\s*(?:be\s*)?less\s*than\s*HK\$\s*([\d.,]+)', re.S | re.I), 'hl'),
    (re.compile(r'not\s*exceed\s*HK\$\s*([\d.,]+)[^%]{0,400}?not\s*(?:be\s*)?less\s*than\s*HK\$\s*([\d.,]+)', re.S | re.I), 'hl'),
    # "indicative Offer Price range of HK$17.00 to HK$22.00" -> (low, high)
    (re.compile(r'indicative\s+[Oo]ffer\s+[Pp]rice\s+range\s+of\s+HK\$\s*([\d.,]+)\s*to\s*HK\$\s*([\d.,]+)', re.S), 'lh'),
    (re.compile(r'[Oo]ffer\s*[Pp]rice\s*[Rr]ange:?\s*HK\$\s*([\d.,]+)\s*(?:to|–|-)\s*HK\$\s*([\d.,]+)', re.S), 'lh'),
]
FIXED_PAT = re.compile(r'(?:Offer|Placing|Final)\s*Price\s*:?\s*HK\$\s*([\d.,]+)\s*per\s*(?:[A-Za-z]+\s*){0,2}Shares?', re.S | re.I)
# 2025+ practice (esp. A+H): cover states only a cap, no range low
MAX_ONLY_PAT = re.compile(r'maximum\s*(?:offer|placing)\s*price\s*(?:of|:)?\s*HK\$\s*([\d.,]+)', re.S | re.I)
# market-cap table: "Based on an Offer Price of HK$X per H Share ... HK$Y per H Share"
# recovers full range for max-only covers; two distinct values => (low, high)
MKT_TABLE_PAT = re.compile(r'Based\s*on\s*an?\s*Offer\s*Price\s*of\s*HK\$\s*([\d.,]+)', re.S | re.I)


# cover with only a cap inside the price slot: "Offer Price : Not more than HK$X per..."
MAX_COVER_PAT = re.compile(r'Offer\s*Price\s*:?\s*Not\s*more\s*than\s*HK\$\s*([\d.,]+)', re.S | re.I)
NOT_LESS_PAT = re.compile(r'not\s*less\s*than\s*HK\$\s*([\d.,]+)', re.S | re.I)
# fixed price without "per Share": "Offer Price : HK$13.50, plus brokerage"
FIXED_COMMA_PAT = re.compile(r'(?:Offer|Placing|Final)\s*Price\s*:?\s*HK\$\s*([\d.,]+)\s*,\s*plus\s*brokerage', re.S | re.I)


def _preceded_by_maximum(text, start):
    """True if the match at `start` is part of 'Maximum Offer Price' (words may be merged)."""
    ctx = re.sub(r'\s+', '', text[max(0, start - 12):start]).lower()
    return ctx.endswith('maximum')


def get_stock_id(sess, code):
    r = sess.get(HOST + '/search/prefix.do',
                 params=dict(callback='cb', lang='EN', type='A', name=code, market='SEHK'),
                 timeout=30)
    txt = r.text
    j = json.loads(txt[txt.index('(') + 1:txt.rindex(')')])
    for s in j.get('stockInfo', []):
        if s['code'] == code:
            return s['stockId']
    return None


def search_docs(sess, stock_id, from_d, to_d):
    p = dict(sortDir='0', sortByOptions='DateTime', category='0', market='SEHK',
             documentType='-1', title='', searchType='1', t1code='-2', t2Gcode='-2', t2code='-2',
             rowRange='100', lang='E', stockId=str(stock_id), fromDate=from_d, toDate=to_d)
    r = sess.get(HOST + '/search/titleSearchServlet.do', params=p, timeout=30)
    j = r.json()
    if j.get('result') in (None, 'null'):
        return []
    return json.loads(j['result'])


def pick_prospectus(docs):
    """Return up to 3 prospectus candidate docs, largest PDF first (fallback on
    scanned/image PDFs with no extractable text)."""
    cands = [d for d in docs if PROSP_TITLE.search(d['TITLE']) and not EXCLUDE_TITLE.search(d['TITLE'])]
    pdfs = [d for d in cands if d['FILE_LINK'].lower().endswith('.pdf')]
    if not pdfs:
        return []
    def size_kb(d):
        m = re.match(r'([\d,]+(?:\.\d+)?)\s*(KB|MB|GB)', d.get('FILE_INFO', ''), re.I)
        if not m:
            return 0
        v = float(m.group(1).replace(',', ''))
        mult = {'KB': 1, 'MB': 1024, 'GB': 1024 * 1024}[m.group(2).upper()]
        return v * mult
    return sorted(pdfs, key=size_kb, reverse=True)[:3]


def extract_range_from_pdf(content, max_pages=80):
    import pdfplumber
    snippet = None
    with pdfplumber.open(io.BytesIO(content)) as doc:
        n = min(len(doc.pages), max_pages)
        for i in range(n):
            text = doc.pages[i].extract_text() or ''
            for pat, order in RANGE_PATS:
                m = pat.search(text)
                if m:
                    a, b = (float(m.group(k).replace(',', '').strip('.')) for k in (1, 2))
                    low, high = (b, a) if order == 'hl' else (a, b)
                    snippet = re.sub(r'\s+', ' ', text[max(0, m.start()-60):m.end()+60])
                    return low, high, snippet, i
    return None, None, None, -1


def detect_fixed(text_pages):
    for t in text_pages:
        for m in FIXED_PAT.finditer(t):
            if _preceded_by_maximum(t, m.start()):
                continue
            return float(m.group(1).replace(',', ''))
        m = FIXED_COMMA_PAT.search(t)
        if m:
            return float(m.group(1).replace(',', ''))
    return None


def detect_mkt_table_range(text_pages):
    """Recover range from market-cap table pages: trigger on despaced
    'Based on an Offer Price of', then collect HK$ amounts tied to 'per...Share'."""
    vals = set()
    per_share = re.compile(r'HK\$\s*([\d.,]+)')
    for t in text_pages:
        despaced = re.sub(r'\s+', '', t).lower()
        if 'basedonanoffer' not in despaced or 'marketcap' not in despaced:
            continue
        for m in per_share.finditer(t):
            tail = re.sub(r'\s+', '', t[m.end():m.end() + 60]).lower()
            if re.match(r'(hk\$[\d.,]+)*per[a-z]*shares?', tail):
                vals.add(float(m.group(1).replace(',', '').strip('.')))
    vals = sorted(vals)
    if len(vals) >= 2:
        return vals[0], vals[-1]
    return None, None


def _analyze_pdf(content, out, max_pages):
    """Try all extraction strategies on one prospectus PDF.
    Returns True if a definitive status was set on `out`, False on parse_fail."""
    low, high, snippet, page_idx = extract_range_from_pdf(content, max_pages)
    if low and high and low <= high:
        out.update(status='ok', low=low, high=high, snippet=snippet[:400])
        return True
    import pdfplumber
    pages_text = []
    with pdfplumber.open(io.BytesIO(content)) as d:
        for i in range(min(40, len(d.pages))):
            pages_text.append(d.pages[i].extract_text() or '')
    if not any(pages_text):
        return False  # scanned/image PDF, no extractable text
    # market-cap table range recovery (max-only covers with full range inside)
    mlow, mhigh = detect_mkt_table_range(pages_text)
    if mlow and mhigh and mlow < mhigh:
        out.update(status='ok_mktcap', low=mlow, high=mhigh,
                   snippet=f'mktcap table: {mlow} / {mhigh}')
        return True
    fx = detect_fixed(pages_text[:10])
    if fx:
        out.update(status='fixed', fixed=fx, snippet=None)
        return True
    # max-price-only offer (no published range low)
    for t in pages_text:
        mm = MAX_ONLY_PAT.search(t)
        if mm:
            out.update(status='max_only', fixed=float(mm.group(1).replace(',', '').strip('.')),
                       snippet=re.sub(r'\s+', ' ', t[max(0, mm.start()-40):mm.end()+80])[:400])
            return True
    # cover cap-only: "Offer Price : Not more than HK$X ..." — try to pair with
    # a "not less than HK$Y" elsewhere in the doc; else treat as max_only
    cap = None
    for t in pages_text:
        mm = MAX_COVER_PAT.search(t)
        if mm:
            cap = float(mm.group(1).replace(',', '').strip('.'))
            break
    if cap:
        for t in pages_text:
            mm = NOT_LESS_PAT.search(t)
            if mm:
                floor = float(mm.group(1).replace(',', '').strip('.'))
                if 0 < floor <= cap:
                    out.update(status='ok', low=floor, high=cap,
                               snippet=f'cover cap {cap} + not-less-than {floor}')
                    return True
                break
        out.update(status='max_only', fixed=cap, snippet=f'cover cap only: {cap}')
        return True
    return False


def process_one(sess, code, listing_date, max_pages=80):
    """Returns dict with status and extracted fields."""
    out = dict(ticker_code=code, listing_date=str(listing_date), status='error',
               low=None, high=None, fixed=None, doc_url=None, snippet=None)
    try:
        sid = get_stock_id(sess, code)
        if not sid:
            out['status'] = 'no_stock_id'
            return out
        out['stock_id'] = sid
        ld = listing_date
        from_ts = time.mktime(time.strptime(str(ld), '%Y-%m-%d')) - 70 * 86400
        from_d = time.strftime('%Y%m%d', time.gmtime(from_ts))
        to_d = ld.strftime('%Y%m%d')
        docs = search_docs(sess, sid, from_d, to_d)
        cands = pick_prospectus(docs)
        if not cands:
            out['status'] = 'no_prospectus_doc'
            out['n_docs'] = len(docs)
            return out
        for doc in cands:
            url = HOST + doc['FILE_LINK']
            r = sess.get(url, timeout=180)
            if r.status_code != 200 or not r.content.startswith(b'%PDF'):
                continue
            if _analyze_pdf(r.content, out, max_pages):
                out['doc_url'] = url
                return out
        out['status'] = 'parse_fail'
        out['doc_url'] = HOST + cands[0]['FILE_LINK']
        return out
    except Exception as e:
        out['status'] = 'error'
        out['error'] = str(e)[:300]
        return out
