#!/usr/bin/env python3
"""
news_scopes.py — shared scope-tagging, risk-keyword and hashing logic for
pipeline C (news). Imported by bronze/news/ingest_news.py,
silver/news/clean_news.py, bronze/news/backfill_historical_news.py and
gold/market/build_news_sentiment_daily.py.

Scopes: US / HK / CRYPTO / FX / METAL (matches gold.news_sentiment_daily check).
An item may carry MULTIPLE scopes — matches are a union of the feed's primary
scope hint and keyword hits on headline+body.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata

SCOPES = ('US', 'HK', 'CRYPTO', 'FX', 'METAL')

# --- Entity / scope keyword dictionary -------------------------------------
# Order matters only for entity_name extraction (first hit wins).
SCOPE_PATTERNS = {
    'US': [
        r'\bS&P\s?500\b', r'\bS&P\b', r'\bNasdaq\b', r'\bDow Jones\b', r'\bDow\b',
        r'\bWall Street\b', r'\bFederal Reserve\b', r'\bFed\b', r'\bFOMC\b',
        r'\bTreasury\b', r'\bTreasuries\b', r'\bTreasurys\b', r'\bpayrolls\b',
        r'\bnonfarm\b', r'\bNFP\b', r'\bCPI\b', r'\binflation report\b',
        r'\bSPY\b', r'\bQQQ\b', r'\bU\.?S\.?\s+(stocks|equities|markets|economy)\b',
        r'\bNYSE\b', r'\bSEC\b', r'\bPowell\b',
    ],
    'HK': [
        r'\bHang Seng\b', r'\bHSI\b', r'\bHSCEI\b', r'\bHKEX\b', r'\bHong Kong\b',
        r'\bHSBC\b', r'\bTencent\b', r'\bAIA\b', r'\bMeituan\b', r'\bAlibaba\b',
        r'\bHKD\b', r'\bH-?shares\b', r'\bChina (stocks|shares|equities|markets)\b',
        r'\bPBOC\b', r'\bHKMA\b', r'\bXiaomi\b', r'\bBYD\b', r'\bJD\.com\b',
    ],
    'CRYPTO': [
        r'\b[Bb]itcoin\b', r'\bBTC\b', r'\b[Ee]thereum\b', r'\bETH\b',
        r'\bcrypto(currency|currencies)?\b', r'\bblockchain\b', r'\bstablecoins?\b',
        r'\bBinance\b', r'\bCoinbase\b', r'\bSolana\b', r'\bXRP\b', r'\bRipple\b',
        r'\btoken(s|ized|ization)?\b', r'\bDeFi\b', r'\bETF inflows?\b',
    ],
    'FX': [
        r'\bforex\b', r'\bFX\b', r'\bEUR/?USD\b', r'\bUSD/?JPY\b', r'\bGBP/?USD\b',
        r'\bUSD/?CN[HY]\b', r'\beuro\b', r'\byen\b', r'\bDXY\b', r'\bdollar index\b',
        r'\bdollar\b', r'\bcurrenc(y|ies)\b', r'\bECB\b', r'\bBOJ\b', r'\bBOE\b',
        r'\bpound\b', r'\bsterling\b', r'\bSwiss franc\b', r'\bcentral banks?\b',
    ],
    'METAL': [
        r'\bgold\b', r'\bsilver\b', r'\bcopper\b', r'\bplatinum\b', r'\bpalladium\b',
        r'\bbullion\b', r'\bXAU\b', r'\bXAG\b', r'\bprecious metals?\b',
        r'\bgold prices?\b', r'\bmining stocks?\b',
    ],
}

_COMPILED = {
    scope: [re.compile(p, re.IGNORECASE) for p in pats]
    for scope, pats in SCOPE_PATTERNS.items()
}

# --- Risk keywords (frame doc: war, default, sanctions, crash, hike,
#     recession, bailout…) — count = number of distinct patterns hitting ------
RISK_KEYWORDS = [
    r'\bwar\b', r'\bwars\b', r'\binvasion\b', r'\bsanctions?\b', r'\bembargo\b',
    r'\bdefault(s|ed|ing)?\b', r'\bbailout(s|ed)?\b', r'\bcrash(es|ed|ing)?\b',
    r'\bcollapse(s|d)?\b', r'\brecession(s|ary)?\b', r'\brate hikes?\b',
    r'\bhikes? rates?\b', r'\bbankrupt(cy|cies)?\b', r'\bcontagion\b',
    r'\bdowngrade(s|d)?\b', r'\bsell-?offs?\b', r'\bplunge(s|d)?\b',
    r'\bturmoil\b', r'\bcrisis\b', r'\bcrises\b', r'\btariffs?\b',
    r'\bmissile(s)?\b', r'\bcoup\b', r'\bbank failures?\b',
    r'\bliquidity crunch\b', r'\bmargin calls?\b', r'\bterroris[tm]\b',
    r'\bstrike(s)?\b on\b', r'\bceasefire\b', r'\bnuclear\b', r'\bdefault risk\b',
    r'\bdebt ceiling\b', r'\bgovernment shutdown\b', r'\blayoffs?\b',
    r'\bjob cuts?\b', r'\bplummet(s|ed)?\b', r'\brout\b', r'\bslump(s|ed)?\b',
]
_RISK_COMPILED = [re.compile(p, re.IGNORECASE) for p in RISK_KEYWORDS]


def normalize_text(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace — for stable hashing."""
    if not s:
        return ''
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', s.strip().lower())


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def strip_html(text: str | None) -> str:
    """Reduce an HTML-bearing RSS summary/body to plain text (kanban
    t_2b413d87): drop tags, unescape entities, collapse whitespace."""
    if not text:
        return ''
    import html as _html
    plain = _TAG_RE.sub(' ', text)
    plain = _html.unescape(plain)
    return _WS_RE.sub(' ', plain).strip()


def url_hash(url: str | None, headline: str) -> str:
    """Dedupe key: canonical url when present, else normalized headline."""
    if url:
        u = url.strip().lower()
        u = re.sub(r'^https?://(www\.)?', '', u)
        u = u.split('?')[0].split('#')[0].rstrip('/')
        if u:
            return sha256('url:' + u)
    return sha256('hl:' + normalize_text(headline))


def headline_hash(headline: str) -> str:
    return sha256('hl:' + normalize_text(headline))


def tag_scopes(headline: str, body: str | None = None, hint: str | None = None) -> list[str]:
    """Union of feed scope hint + keyword hits on headline+body.

    Headline hits count double via a second pass only for entity extraction;
    for scope membership a single hit anywhere suffices.
    """
    text = headline or ''
    if body:
        text = text + '\n' + body[:2000]
    scopes = set()
    if hint in SCOPES:
        scopes.add(hint)
    for scope, pats in _COMPILED.items():
        if any(p.search(text) for p in pats):
            scopes.add(scope)
    return sorted(scopes)


def extract_entity(headline: str, body: str | None = None) -> str | None:
    """First matched canonical keyword, for the entity_name column."""
    text = headline or ''
    if body:
        text = text + '\n' + body[:1000]
    for scope in SCOPES:
        for p in _COMPILED[scope]:
            m = p.search(text)
            if m:
                return m.group(0)[:100]
    return None


def risk_hit_count(headline: str, body: str | None = None) -> int:
    text = headline or ''
    if body:
        text = text + '\n' + body[:2000]
    return sum(1 for p in _RISK_COMPILED if p.search(text))


# --- Language tagging (t_69e09f53) ------------------------------------------
# silver.historical_news.lang is an ISO 639-1 code. At ingest we take GDELT's
# article `language` metadata (full English name) and normalize it; anything
# unmapped falls back to the Unicode-script heuristic, which is also used to
# backfill legacy rows.

GDELT_LANG_MAP = {
    'english': 'en', 'chinese': 'zh', 'arabic': 'ar', 'hindi': 'hi',
    'urdu': 'ur', 'korean': 'ko', 'japanese': 'ja', 'russian': 'ru',
    'french': 'fr', 'german': 'de', 'spanish': 'es', 'portuguese': 'pt',
    'italian': 'it', 'dutch': 'nl', 'polish': 'pl', 'ukrainian': 'uk',
    'hebrew': 'he', 'thai': 'th', 'vietnamese': 'vi', 'indonesian': 'id',
    'malay': 'ms', 'turkish': 'tr', 'persian': 'fa', 'farsi': 'fa',
    'bengali': 'bn', 'tamil': 'ta', 'telugu': 'te', 'marathi': 'mr',
    'gujarati': 'gu', 'kannada': 'kn', 'malayalam': 'ml', 'punjabi': 'pa',
    'nepali': 'ne', 'sinhala': 'si', 'burmese': 'my', 'khmer': 'km',
    'lao': 'lo', 'georgian': 'ka', 'armenian': 'hy', 'amharic': 'am',
    'somali': 'so', 'swahili': 'sw', 'zulu': 'zu', 'greek': 'el',
    'czech': 'cs', 'slovak': 'sk', 'hungarian': 'hu', 'romanian': 'ro',
    'bulgarian': 'bg', 'serbian': 'sr', 'croatian': 'hr', 'slovenian': 'sl',
    'finnish': 'fi', 'swedish': 'sv', 'norwegian': 'no', 'danish': 'da',
    'catalan': 'ca', 'estonian': 'et', 'latvian': 'lv', 'lithuanian': 'lt',
    'icelandic': 'is', 'pashto': 'ps', 'oriya': 'or', 'assamese': 'as',
}

# Unicode block -> ISO code, checked in order. CJK ideographs are shared
# between zh/ja, so kana is tested first: any kana presence wins Japanese.
_SCRIPT_BLOCKS = [
    ('ja', ((0x3040, 0x30FF),)),                       # hiragana + katakana
    ('ko', ((0xAC00, 0xD7AF), (0x1100, 0x11FF),
            (0x3130, 0x318F))),                        # hangul
    ('zh', ((0x4E00, 0x9FFF), (0x3400, 0x4DBF),
            (0xF900, 0xFAFF), (0x20000, 0x2A6DF))),    # CJK ideographs
    ('ar', ((0x0600, 0x06FF), (0x0750, 0x077F),
            (0x08A0, 0x08FF), (0xFB50, 0xFDFF))),      # arabic
    ('hi', ((0x0900, 0x097F),)),                       # devanagari
    ('bn', ((0x0980, 0x09FF),)),
    ('pa', ((0x0A00, 0x0A7F),)),
    ('gu', ((0x0A80, 0x0AFF),)),
    ('ta', ((0x0B80, 0x0BFF),)),
    ('te', ((0x0C00, 0x0C7F),)),
    ('kn', ((0x0C80, 0x0CFF),)),
    ('ml', ((0x0D00, 0x0D7F),)),
    ('si', ((0x0D80, 0x0DFF),)),
    ('th', ((0x0E00, 0x0E7F),)),
    ('lo', ((0x0E80, 0x0EFF),)),
    ('my', ((0x1000, 0x109F),)),
    ('km', ((0x1780, 0x17FF),)),
    ('ru', ((0x0400, 0x04FF),)),                       # cyrillic
    ('el', ((0x0370, 0x03FF),)),
    ('he', ((0x0590, 0x05FF),)),
    ('hy', ((0x0530, 0x058F),)),
    ('ka', ((0x10A0, 0x10FF),)),
    ('am', ((0x1200, 0x137F),)),                       # ethiopic
]


def detect_lang(text: str | None) -> str | None:
    """Unicode-script heuristic -> ISO 639-1. Latin-script text returns 'en'
    (fr/de/es/vi are indistinguishable at script level — acceptable per the
    t_69e09f53 spec). Returns None when no letters are found."""
    counts: dict[str, int] = {}
    latin = 0
    for ch in text or '':
        cp = ord(ch)
        if cp < 0x300:
            if ch.isalpha():
                latin += 1
            continue
        for code, blocks in _SCRIPT_BLOCKS:
            if any(lo <= cp <= hi for lo, hi in blocks):
                counts[code] = counts.get(code, 0) + 1
                break
    # kana presence => Japanese even when ideographs dominate
    if counts.get('ja'):
        return 'ja'
    if counts:
        return max(counts.items(), key=lambda kv: kv[1])[0]
    return 'en' if latin else None


def normalize_lang(gdelt_language: str | None,
                   headline: str | None = None) -> str | None:
    """GDELT `language` field (full English name) -> ISO code, falling back to
    the script heuristic on the headline."""
    if gdelt_language:
        code = GDELT_LANG_MAP.get(gdelt_language.strip().lower())
        if code:
            return code
    return detect_lang(headline)
