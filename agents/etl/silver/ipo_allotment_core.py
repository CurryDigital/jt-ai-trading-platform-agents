#!/usr/bin/env python3
"""ipo_allotment_core.py — HK IPO allotment-results announcement parser.

Source: HKEXnews "ALLOTMENT RESULTS" announcements. Since at least 2024 these
follow a standardized template:
  * "ALLOTMENT RESULTS DETAILS" summary box (valid/successful applications,
    Subscription level, Claw-back triggered, initial/reallocated/final HKPO
    shares, % of Global Offering)  -> clawback + final retail tranche
  * "BASIS OF ALLOCATION UNDER THE HONG KONG PUBLIC OFFERING" tier tables
    (Pool A / Pool B; rows: shares applied for, valid applications, basis of
    allotment/ballot, approximate % allotted)  -> one-lot win rate + tiers

The tier tables have NO ruling lines, so pdfplumber.extract_tables() finds
nothing — rows are parsed from extract_text() on flattened page text.

Code-reuse guard: HKEX recycles stock codes (e.g. 2550 RREEF->SHEIN). The
prefix.do stockInfo list can hold several issuers for one code; we try every
matching stockId and keep the one whose date window contains an allotment doc.

Used by: silver/backfill_ipo_allotment.py (kanban t_49215d54, 2026-09-03).
"""
import os, re, io, sys, json, time

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/silver'))

from ipo_price_range_core import search_docs, HEADERS, HOST  # noqa: E402

ALLOT_TITLE = re.compile(r'ALLOTMENT RESULTS', re.I)
EXCLUDE_TITLE = re.compile(r'STABILIZ|OVER-ALLOTMENT|CLARIFICATION|SUPPLEMENT', re.I)

INT_RE = r'([\d,]{1,15})'


def _i(s):
    if not s:
        return None
    s = s.replace(',', '').strip()
    return int(s) if s.isdigit() else None


def _f(s):
    if not s:
        return None
    s = s.replace(',', '').strip()
    try:
        return float(s)
    except ValueError:
        return None


def get_stock_ids(sess, code):
    """All stockIds whose code matches (code reuse returns several issuers)."""
    r = sess.get(HOST + '/search/prefix.do',
                 params=dict(callback='cb', lang='EN', type='A', name=code,
                             market='SEHK'), timeout=30)
    txt = r.text
    j = json.loads(txt[txt.index('(') + 1:txt.rindex(')')])
    return [s['stockId'] for s in j.get('stockInfo', []) if s['code'] == code]


def find_allot_doc(sess, code, listing_date):
    """Return (cand_doc, stock_id, n_docs). Tries every stockId for the code
    until one yields an allotment-results doc in the window listing-15d..+2d."""
    from_ts = time.mktime(time.strptime(str(listing_date), '%Y-%m-%d')) - 15 * 86400
    from_d = time.strftime('%Y%m%d', time.gmtime(from_ts))
    to_ts = time.mktime(time.strptime(str(listing_date), '%Y-%m-%d')) + 2 * 86400
    to_d = time.strftime('%Y%m%d', time.gmtime(to_ts))
    sids = get_stock_ids(sess, code)
    if not sids:
        return None, None, 0
    fallback = None
    for sid in sids:
        docs = search_docs(sess, sid, from_d, to_d)
        cands = [d for d in docs
                 if ALLOT_TITLE.search(d['TITLE'])
                 and not EXCLUDE_TITLE.search(d['TITLE'])
                 and d['FILE_LINK'].lower().endswith('.pdf')]
        if cands:
            return cands[0], sid, len(docs)
        if docs and fallback is None:
            fallback = (sid, len(docs))
    return None, (fallback[0] if fallback else sids[0]), (fallback[1] if fallback else 0)


def _section(flat, start_kw, end_kws):
    i = flat.upper().find(start_kw)
    if i < 0:
        return ''
    j = len(flat)
    for kw in end_kws:
        k = flat.upper().find(kw, i + len(start_kw))
        if 0 < k < j:
            j = k
    return flat[i:j]


# intl section header: 'INTERNATIONAL OFFER(ING)' / 'PLACING' immediately
# followed by 'No. of placees' — avoids cutting the retail block at sentences
# like 'reallocated to the International Offer (claw-forward)'.
INTL_HDR = re.compile(
    r'(?:INTERNATIONAL\s+OFFER\w*|PLACING)\s+No\.?\s*of\s+placees', re.I)


def _grab(pat, text, cast=_f, flags=re.I):
    m = re.search(pat, text, flags)
    return cast(m.group(1)) if m else None


def parse_summary(flat):
    """Parse the ALLOTMENT RESULTS DETAILS summary box (retail + intl)."""
    out = {}
    box = _section(flat, 'ALLOTMENT RESULTS DETAILS',
                   ['LOCK-UP', 'BASIS OF ALLOCATION', 'DESPATCH'])
    if not box:
        return out
    retail_end = None
    m_hdr = INTL_HDR.search(box)
    if m_hdr:
        retail_end = m_hdr.start()
    retail = box[:retail_end] if retail_end else box
    intl = box[m_hdr.start():] if m_hdr else ''

    out['retail_valid_applications'] = _grab(
        r'No\.\s*of valid applications\s*' + INT_RE, retail, _i)
    out['retail_successful_applications'] = _grab(
        r'No\.\s*of successful applications\s*' + INT_RE, retail, _i)
    out['oversub_retail_ann'] = _grab(
        r'Subscription\s+[Ll]evel\s*([\d,.]+)\s*times', retail)
    claw = re.search(r'(?:Claw-?\s*back triggered|Re-?\s*allocation)\s*(Yes|No)',
                     retail, re.I)
    if claw:
        out['clawback_triggered'] = claw.group(1).lower() == 'yes'
    out['retail_shares_initial'] = _grab(
        r'initially available under the[^0-9]{0,60}?' + INT_RE, retail, _i)
    # reallocation line: number may sit inside or after a wrapped '(claw-back)'
    # note; 'from' = intl->retail (positive), 'to' = retail->intl (negative).
    # value may be 'N/A' or a bare '0' — both mean no reallocation.
    m = re.search(r'reallocated\s+(from|to)\s+the.{0,80}?((?-i:N/?A)|0(?!\d)|[\d,]{4,})',
                  retail, re.I)
    if m and 'N' not in m.group(2).upper().replace('/', ''):
        v = _i(m.group(2))
        out['retail_shares_reallocated'] = v if m.group(1).lower() == 'from' else -v
    out['retail_shares_final'] = _grab(
        r'Final\s+(?:no\.|number) of Offer Shares under the[^0-9]{0,90}?' + INT_RE,
        retail, _i)
    out['retail_pct_final'] = _grab(
        r'%\s*of Offer Shares under the[^0-9]{0,90}?([\d.]+)\s*%', retail)
    if intl:
        out['oversub_intl_ann'] = _grab(
            r'Subscription\s+[Ll]evel\s*([\d,.]+)\s*times', intl)
    return {k: v for k, v in out.items() if v is not None}


POOL_TOKEN = re.compile(r'^\s*Pool\s*([AB])\s*[:：]?\s*$', re.I)
PCT_TAIL = re.compile(r'([\d.]+)\s*%$')
# ballot core is layout-stable; the "to ... receive N shares" tail can wrap
# anywhere (or land on the next line entirely), so capture it loosely.
BALLOT_CORE = re.compile(r'([\d,]+)\s+out\s+of\s+([\d,]+)(?:\s+applicat\w*)?', re.I)
BALLOT_CLAUSE = re.compile(
    r'([\d,]+)\s+out\s+of\s+([\d,]+)(?:\s+applicat\w*)?\s+to\s+(.*?)'
    r'receive\s+(?:an\s+additional\s+)?([\d,]+)\s*(?:[Hh]\s*)?[Ss]hares?|'
    r'([\d,]+)\s+out\s+of\s+([\d,]+)(?:\s+applicat\w*)?(?:\s+to)?', re.I)
RECV_RE = re.compile(r'receive\s+(?:an\s+additional\s+)?([\d,]+)', re.I)
BASE_SHARES = re.compile(r'([\d,]+)\s*(?:[Hh]\s*)?[Ss]hares?')
NUM_RE = re.compile(r'[\d,]+')
TOTAL_MARK = re.compile(r'Total\s+number of|^Total\b', re.I)
STOP_LINE = re.compile(
    r'As of the date of this announcement|DESPATCH|Results of [Aa]pplications|'
    r'LOCK-UP|Refund [Cc]heques', re.I)

# "0 H Shares" two-line loser/winner format (e.g. 6181.HK): each tier prints
#   '100 8,000 0 H Shares'      (losing applications)
#   '3.39%'                     (tier pct on its own line)
#   '100 281 100 H Shares'      (winning applications)
ZERO_LOSER = re.compile(r'^([\d,]+)\s+([\d,]+)\s+0\s+(?:[Hh]\s*)?[Ss]hares?$')
PCT_ONLY = re.compile(r'^([\d.]+)\s*%$')
WINNER_LINE = re.compile(
    r'^([\d,]+)\s+([\d,]+)\s+([\d,]+)\s+(?:[Hh]\s*)?[Ss]hares?$')


def _merge_zero_share_triples(lines):
    """Rewrite loser/pct/winner triples into one standard ballot line."""
    out = []
    i = 0
    while i < len(lines):
        m0 = ZERO_LOSER.match(lines[i].strip())
        if m0 and i + 2 < len(lines):
            mp = PCT_ONLY.match(lines[i + 1].strip())
            mw = WINNER_LINE.match(lines[i + 2].strip())
            if mp and mw and _i(mw.group(1)) == _i(m0.group(1)):
                losers = _i(m0.group(2))
                winners = _i(mw.group(2))
                sh = _i(mw.group(3))
                tot = losers + winners
                out.append(f"{m0.group(1)} {tot:,} {winners:,} out of {tot:,} "
                           f"applicants to receive {sh:,} shares {mp.group(1)}%")
                i += 3
                continue
        out.append(lines[i])
        i += 1
    return out


def _parse_buf(buf):
    """Parse one complete row buffer (ends with '%').

    Layout-tolerant: extracts the ballot clause first (wherever it landed),
    then recovers shares_applied / valid_applications from the leftover
    numbers. valid_applications must equal the ballot denominator when a
    ballot exists; shares_applied is the leftover number that isn't the
    denominator (checking any digits captured inside the clause too — the
    02505 layout wraps the applied-for column into the ballot line).
    """
    m = PCT_TAIL.search(buf)
    if not m:
        return None
    pct = float(m.group(1))
    body = buf[:m.start()]
    winners = applicants = None
    clause_nums = []
    recv_shares = None
    mc = BALLOT_CLAUSE.search(body)
    if mc:
        if mc.group(1):  # full clause with 'receive N shares'
            winners = _i(mc.group(1)); applicants = _i(mc.group(2))
            clause_nums = [_i(x) for x in NUM_RE.findall(mc.group(3) or '')]
            recv_shares = _i(mc.group(4))
        else:
            winners = _i(mc.group(5)); applicants = _i(mc.group(6))
        body_wo = body[:mc.start()] + ' ' + body[mc.end():]
        if recv_shares is None:
            mr = RECV_RE.search(body_wo)
            if mr:
                recv_shares = _i(mr.group(1))
    else:
        body_wo = body
    bases = [_i(b.group(1)) for b in BASE_SHARES.finditer(body_wo)]
    rest = BASE_SHARES.sub(' ', body_wo)
    nums = [n for n in (_i(x) for x in NUM_RE.findall(rest)) if n is not None]
    nums += [n for n in clause_nums if n is not None]
    applied = valid = None
    if applicants is not None:
        # scrambled wraps can pair the winners with the wrong denominator
        # (e.g. "10,518 out of 100 105,175 ..."). A ballot can never have
        # more winners than applicants — re-pair with a leftover number.
        if winners is not None and winners > applicants:
            cands = sorted(n for n in nums if n >= winners)
            if cands:
                applicants = cands[0]
            else:
                winners = applicants = None
    if applicants is not None:
        valid = applicants
        others = [n for n in nums if n != applicants]
        applied = min(others) if others else None
    elif len(nums) >= 2:
        applied, valid = nums[0], nums[1]
    elif nums:
        applied = nums[0]
    basis = re.sub(r'\s+', ' ', body).strip()[:300]
    if TOTAL_MARK.search(basis) or len(basis) < 3:
        return None
    row = {'shares_applied': applied,
           'valid_applications': valid,
           'basis': basis,
           'approx_pct_allotted': pct}
    if winners is not None:
        row['ballot_winners'] = winners
        row['ballot_applicants'] = applicants
    if recv_shares is not None:
        row['base_allotment_shares'] = recv_shares
    elif bases:
        row['base_allotment_shares'] = bases[0]
    return row


def parse_tier_tables(lines):
    """Line-based parse of the BASIS OF ALLOCATION section.

    Rows accumulate into a buffer until a line ends with '%' (the pct column
    always terminates a row). Accumulation only STARTS on lines beginning
    with a number, so intro prose containing digits (e.g. '... 15,747 valid
    applications ...') cannot poison the first row. '0 Shares' loser/winner
    triples are pre-merged. Pools: 'Pool A' / 'Pool B' (optional colon).
    Returns {'pool_a': [...], 'pool_b': [...]}; pools absent from the doc are
    simply missing keys (single-pool GEM/small offers -> pool_a only).
    """
    start = None
    for i, ln in enumerate(lines):
        if 'BASIS OF ALLOCATION' in ln.upper():
            start = i
            break
    if start is None:
        return {}
    seg = _merge_zero_share_triples(lines[start + 1:])
    out = {}
    pool = 'pool_a'
    buf = ''
    for ln in seg:
        s = ln.strip()
        if not s:
            continue
        if STOP_LINE.search(s):
            break
        pm = POOL_TOKEN.match(s)
        if pm:
            buf = ''
            pool = 'pool_' + pm.group(1).lower()
            continue
        if not re.search(r'\d', s):
            continue  # column header / prose
        if not buf and not re.match(r'^[\d,]', s):
            continue  # prose containing digits — never starts a row
        buf = (buf + ' ' + s).strip()
        if buf.endswith('%'):
            row = _parse_buf(buf)
            if row:
                out.setdefault(pool, []).append(row)
            buf = ''
    # sanity per pool: shares_applied non-decreasing, else truncate tail junk
    for key in list(out):
        clean = []
        last = 0
        for r in out[key]:
            if r['shares_applied'] is None:
                clean.append(r)
                continue
            if r['shares_applied'] < last:
                break
            last = r['shares_applied']
            clean.append(r)
        out[key] = clean
    return {k: v for k, v in out.items() if v}


def one_lot_win_rate(pools):
    """Pool-A first tier win probability (%).

    Ballot -> 100*winners/applicants (exact). No ballot: full allotment of
    the tier -> 100; partial fixed allotment (base < applied, rare at tier 1)
    -> approx_pct_allotted as the effective fill ratio.
    """
    pa = pools.get('pool_a') or []
    if not pa:
        return None
    r0 = pa[0]
    if r0.get('ballot_winners') is not None and r0.get('ballot_applicants'):
        v = 100.0 * r0['ballot_winners'] / r0['ballot_applicants']
        return round(min(v, 100.0), 2)
    ap = r0.get('shares_applied')
    base = r0.get('base_allotment_shares')
    if base:
        if ap is None or base >= ap:
            return 100.0
        return r0.get('approx_pct_allotted')
    return None


def parse_announcement(content):
    """Full parse of one allotment-results PDF. Returns dict of fields."""
    import pdfplumber
    texts = []
    with pdfplumber.open(io.BytesIO(content)) as doc:
        n_pages = len(doc.pages)
        for p in doc.pages:
            texts.append(p.extract_text() or '')
    flat = re.sub(r'\s+', ' ', '\n'.join(texts))
    lines = [ln for t in texts for ln in t.split('\n')]
    out = {'n_pages': n_pages}
    out.update(parse_summary(flat))
    pools = parse_tier_tables(lines)
    if pools:
        out['pool_a'] = pools.get('pool_a')
        out['pool_b'] = pools.get('pool_b')
        olr = one_lot_win_rate(pools)
        if olr is not None:
            out['one_lot_win_rate'] = olr
    i = flat.upper().find('ALLOTMENT RESULTS DETAILS')
    if i >= 0:
        out['snippet'] = flat[i:i + 350]
    return out


def process_one(sess, code, listing_date):
    """End-to-end for one IPO. Returns dict with status + fields."""
    out = dict(ticker_code=code, listing_date=str(listing_date), status='error')
    try:
        cand, sid, n_docs = find_allot_doc(sess, code, listing_date)
        out['stock_id'] = sid
        out['n_docs'] = n_docs
        if not sid:
            out['status'] = 'no_stock_id'
            return out
        if not cand:
            out['status'] = 'no_allot_doc'
            return out
        url = HOST + cand['FILE_LINK']
        out['doc_url'] = url
        out['doc_title'] = re.sub(r'\s+', ' ', cand['TITLE']).strip()
        r = sess.get(url, timeout=180)
        if r.status_code != 200 or not r.content.startswith(b'%PDF'):
            out['status'] = 'error'
            out['error'] = f'pdf fetch {r.status_code}'
            return out
        parsed = parse_announcement(r.content)
        out.update(parsed)
        has_table = bool(parsed.get('pool_a'))
        has_summary = bool(parsed.get('oversub_retail_ann') is not None
                           or parsed.get('retail_valid_applications') is not None)
        if has_table and has_summary:
            out['status'] = 'ok'
        elif has_table:
            out['status'] = 'partial_table'
        elif has_summary:
            out['status'] = 'partial_summary'
        else:
            out['status'] = 'parse_fail'
        return out
    except Exception as e:
        out['status'] = 'error'
        out['error'] = str(e)[:300]
        return out
