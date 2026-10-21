#!/usr/bin/env python3
"""
build_news_clusters.py — story-cluster builder for Research > News (kanban
t_d492325f).

Reads:   silver.historical_news (rolling --hours window, scoped by category)
         consumption.news_outlook (row_type='cluster', latest run_date) for the
         optional LLM direction/confidence/rationale layer.
Writes:  consumption.news_clusters (one row per story cluster, members JSONB)

Pipeline (recipe v1, kanban t_0461676c — head-of-feed same-event
fragmentation):
  1. PRE-CLEAN — strip trailing '(copy)' markers, strip boilerplate outlet
     prefix labels ('THE CLOSING BELL :', 'Markets today :') for canonical
     hygiene, drop exact title+outlet dupes, drop rows without a source url
     (contract: every member has url).
  2. EMBED — paraphrase-multilingual-MiniLM-L12-v2 (fastembed/ONNX),
     TITLE-ONLY. Ledes were dropped from the embedding input on evidence
     (t_0461676c): a 200-word outlet-specific lede dilutes the 10-word
     shared title and pushes same-event cross-outlet paraphrases APART
     (0.66 -> 0.57) while inflating same-genre cross-language dailies.
  3. CLUSTER — greedy cosine at threshold 0.82, scoped by asset_class AND
     language scope: EN+ZH form the 'core' scope, every other language is
     its own scope (kills the vi/hi/ar gold-daily mega-blob — multilingual
     embeddings rate cross-language genre twins at 0.70-0.85, so no cosine
     threshold separates them from same-event paraphrases). Generic
     live-blog wraps ('Stock market today: Live updates') and city-rate
     dailies ('Gold prices in Pakistan today – Check 24, 22 & 21 karat
     rates') never merge: they are genres, not events. (v2, t_2113ec95:
     GDELT 'en' lang mislabels are re-detected by script/lexicon/domain
     before scoping, so id/tr gold dailies leave the core scope.)
  4. EVENT MERGE (E6) — union-find over cluster pairs in the same scope
     sharing >= 2 salient tokens (stemmed, len>=3, document-frequency
     <= 8% within the scope so 'stocks/oil/prices' don't count but
     'hormuz/rba/berkshire' do), last-activity within 36h, OVERLAPPING
     activity windows (v2: younger first_seen <= older last_seen + 6h —
     kills multi-day running-wrap chaining), title-centroid cosine >= 0.45
     guard, merged size cap 40.
  4b. E6B SECOND PASS (v2) — on one-event days the event's own tokens
     ('cpi','inflation') exceed the DF cap in SMALL scopes (METAL cap=2-4)
     exactly when they matter most. E6B keeps the 8% DF cap but exempts
     named-event anchor tokens from gold.macro_calendar (US CPI/FOMC/RBA
     dates) on their event day, gated by a higher centroid cosine
     (>= 0.60). A blanket 25% relaxed-DF variant was tried and rejected on
     audit: genre tokens ('bitcoin') chained unrelated stories.
  5. CANONICAL — member from the highest-authority outlet wins; ties break
     to earliest first_seen (AUTHORITY below, wires > aggregators).
  6. ENRICH — driver tags + tickers (member entity_name) + impact_score as
     the exact sum of impact_components {attention, coverage, recency,
     keyword_impact, llm_impact} (kanban t_1f96bc9b; News tooltip renders
     these verbatim)
     + LLM outlook join on cluster_id — qr_research extract_clusters.py
     (--source embedding) copies news_clusters.cluster_id verbatim into
     news_outlook.cluster_key (kanban t_1f95572e / t_9a746bb9).

Run:  etl-news-venv/bin/python consumption/market/build_news_clusters.py [--hours 48] [--dry-run]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

import numpy as np  # noqa: E402
from db import get_connection  # noqa: E402

EMBED_MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
SIM_THRESHOLD = 0.82
ASSET_CLASSES = ['US', 'HK', 'CRYPTO', 'FX', 'METAL']

DDL = """
CREATE TABLE IF NOT EXISTS consumption.news_clusters (
    cluster_id         VARCHAR(32)  NOT NULL,
    window_hours       INTEGER      NOT NULL DEFAULT 48,
    canonical_headline TEXT         NOT NULL,
    story_count        INTEGER      NOT NULL,
    outlet_count       INTEGER      NOT NULL,
    first_seen_utc     TIMESTAMP,
    last_seen_utc      TIMESTAMP,
    asset_class        VARCHAR(8)   NOT NULL,
    driver_tags        TEXT[]       NOT NULL DEFAULT '{}',
    tickers            TEXT[]       NOT NULL DEFAULT '{}',
    llm_direction      VARCHAR(10),
    llm_confidence     NUMERIC(4,3),
    llm_rationale      TEXT,
    impact_score       INTEGER      NOT NULL DEFAULT 0,
    impact_components  JSONB,
    members            JSONB        NOT NULL DEFAULT '[]',
    computed_at        TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (window_hours, cluster_id)
);
ALTER TABLE consumption.news_clusters
    ADD COLUMN IF NOT EXISTS impact_components JSONB;
"""

# Outlet authority ranking: lower wins canonical. Tier 0 wires/top financial
# press, tier 1 major outlets, tier 2 niche/regionals; unlisted = 100.
AUTHORITY = [
    'reuters', 'bloomberg', 'ft.com', 'wsj',                      # tier 0
    'apnews', 'afp', 'cnbc', 'nytimes', 'ft.', 'marketwatch',
    'finance.yahoo', 'scmp', 'aastocks', 'investing.com',         # tier 1
    'coindesk', 'cointelegraph', 'theblock', 'kitco', 'fxstreet', # tier 2
]


def outlet_rank(source: str | None) -> int:
    s = (source or '').replace('gdelt:', '').lower()
    for i, pat in enumerate(AUTHORITY):
        if pat in s:
            return i
    return 100


# --- pre-clean ---------------------------------------------------------------
_COPY_RE = re.compile(r'\s*\((?:copy|コピー)\)\s*$', re.IGNORECASE)
_WS_RE = re.compile(r'\s+')

# Boilerplate outlet prefix labels (kanban t_0461676c E3): 'THE CLOSING
# BELL :', 'Markets today :', 'PYMNTS |', 'Sensex Today | Stock Market LIVE
# Updates :'. Stripped before canonical selection for headline hygiene.
# NOTE: this changes canonicals (and therefore cluster_ids, sha1 of
# canonical) for the ~1% of titles carrying a label — accepted.
_BOILER_HINT = re.compile(r'(today|live|update|bell|brief|wrap|open|close|'
                          r' recap|watchlist|movers|markets at|stock market)',
                          re.I)
_PREFIX_RE = re.compile(r"^([A-Z0-9][A-Za-z0-9 &.,'’\-]{1,58}?)\s*[:|]\s+")


def strip_boilerplate(h: str) -> str:
    out = h
    for _ in range(2):  # chained labels: 'Sensex Today | LIVE Updates : ...'
        m = _PREFIX_RE.match(out)
        if not m:
            break
        label = m.group(1).strip()
        letters = [c for c in label if c.isalpha()]
        caps_ratio = (sum(1 for c in letters if c.isupper()) / len(letters)) \
            if letters else 0
        if caps_ratio >= 0.6 or _BOILER_HINT.search(label):
            out = out[m.end():].strip()
        else:
            break
    return out or h


def normalize_headline(h: str) -> str:
    h = _COPY_RE.sub('', (h or '').strip())
    h = strip_boilerplate(h)
    return _WS_RE.sub(' ', h).strip()


# --- driver tags + impact keywords (mirrors /api/news/digest heuristics) -----
_DRIVERS = [
    ("Oil & Energy", ["oil", "crude", "brent", "wti", "opec", "hormuz"]),
    ("Fed & Rates", ["fed ", "fomc", "powell", "rate hike", "rate cut", "repricing",
                     "yields", "treasury", "bessent", "monetary policy"]),
    ("Inflation & CPI", ["cpi", "inflation", "pce", "payrolls", "jobs report"]),
    ("Geopolitics", ["iran", "russia", "ukraine", "sanction", "irgc", "geopolitic",
                     "putin", "middle east", "tariff", "trade war"]),
    ("Earnings", ["earnings", "eps", "profit", "revenue", "wall street earnings"]),
    ("AI & Tech", [" ai ", "artificial intelligence", "nvidia", "chip", "semiconductor",
                   "data center", "datacenter"]),
    ("Crypto Policy", ["bitcoin", "crypto", "usdc", "stablecoin", "xrp", "defi"]),
    ("China & HK", ["hang seng", "恒指", "港股", "北水", "科指",
                    "china", "pboc", "yuan", "stimulus", "property",
                    "楼", "商厦", "香港"]),
    ("FX & Currency", ["yen", "dollar", "euro", "ringgit", "intervention", "currency",
                       "currencies", "엔화"]),
    ("Metals", ["gold", "silver", "bullion", "黄金", "precious metal"]),
]
_BULL = ["surge", "rally", "soar", "jump", "gain", "rise", "rises", "record high",
         "all-time high", "beat", "beats", "rebound", "higher", "inflows",
         "extends", "breakout", "涨", "揚", "飆", "新高"]
_BEAR = ["slip", "fall", "fell", "drop", "plunge", "slump", "slide", "lower",
         "down", "miss", "fear", "crisis", "crash", "outflow", "retreat",
         "fade", "weigh", "loss", "selloff", "跌", "回调", "沦"]


def driver_tags(text: str, limit: int = 3) -> list:
    h = " " + (text or "").lower() + " "
    return [label for label, kws in _DRIVERS if any(k in h for k in kws)][:limit]


def impact_hits(text: str) -> int:
    low = " " + (text or "").lower() + " "
    return sum(1 for kws in (_BULL, _BEAR) for k in kws if k in low)


# --- ticker extraction (kanban t_03bdbbfa) -----------------------------------
# news_clusters.tickers[] must hold REAL tradable symbols in platform
# (yfinance) convention so the News page can join against positions/watchlist
# and /api/market/delta-since. Entity phrases ('US stocks', 'Gold') are mapped
# through an alias table; anything unmapped is DROPPED, never emitted.
# Acceptance: every emitted value matches TICKER_RE and belongs to the known
# universe (gold.daily_ohlcv tickers UNION open position tickers).
TICKER_RE = re.compile(r'^[A-Z0-9][A-Z0-9.=-]{0,11}$')

# phrase (lowercase, word-boundary matched) -> candidate tickers, in priority
# order. Only candidates present in the known universe are emitted.
TICKER_ALIASES = [
    ('bitcoin', ['BTC-USD']), ('btc', ['BTC-USD']),
    ('ethereum', ['ETH-USD']), ('ether', ['ETH-USD']), ('eth', ['ETH-USD']),
    ('solana', ['SOL-USD']), ('xrp', ['XRP-USD']), ('ripple', ['XRP-USD']),
    ('crypto', ['BTC-USD']), ('cryptocurrencies', ['BTC-USD']),
    ('cryptocurrency', ['BTC-USD']),
    ('gold', ['GC=F', 'GLD']), ('spot gold', ['GC=F']), ('bullion', ['GC=F']),
    ('precious metal', ['GC=F']), ('黄金', ['GC=F']),
    ('silver', ['SI=F', 'SLV']),
    ('copper', ['HG=F']),
    ('crude', ['CL=F', 'USO']), ('wti', ['CL=F']), ('brent', ['CL=F']),
    ('oil', ['CL=F', 'USO']), ('natural gas', ['NG=F']),
    ('nasdaq', ['QQQ']), ('s&p 500', ['SPY']), ('s&p', ['SPY']), ('spx', ['SPY']),
    ('dow jones', ['DIA']), ('dow', ['DIA']),
    ('russell 2000', ['IWM']), ('russell', ['IWM']),
    ('wall street', ['SPY']), ('us stocks', ['SPY']), ('u.s. stocks', ['SPY']),
    ('us markets', ['SPY']), ('u.s. markets', ['SPY']),
    ('hang seng', ['2800.HK']), ('恒指', ['2800.HK']), ('港股', ['2800.HK']),
    ('yen', ['JPY=X']), ('japanese yen', ['JPY=X']),
    ('euro', ['EURUSD=X']), ('pound', ['GBPUSD=X']), ('sterling', ['GBPUSD=X']),
    ('treasuries', ['TLT']), ('treasury yields', ['TLT']), ('bonds', ['TLT']),
    ('high yield', ['HYG']), ('junk bonds', ['HYG']),
    ('emerging markets', ['EEM']),
]
# All-caps tokens that look like symbols but are NOT tickers (macro/news speak).
_CAPS_STOP = {
    'CPI', 'GDP', 'PPI', 'PCE', 'FED', 'FOMC', 'ECB', 'PBOC', 'BOJ', 'BOE',
    'SEC', 'DOJ', 'IMF', 'WTO', 'OPEC', 'ETF', 'IPO', 'CEO', 'CFO', 'FDA',
    'US', 'USA', 'UK', 'EU', 'UN', 'NATO', 'AI', 'EV', 'IPO', 'NFP', 'PMI',
    'ISM', 'ADP', 'QoQ'.upper(), 'YOY', 'MOM', 'ATH', 'ETF', 'USD', 'HKD',
    'CNY', 'RMB', 'GMT', 'UTC', 'HKT', 'NYSE', 'HKEX', 'API', 'WSJ', 'FT',
}
_CASHTAG_RE = re.compile(r'\$([A-Za-z]{1,6}(?:\.[A-Za-z]{1,2})?)')
_HKCODE_RE = re.compile(r'\b(\d{4})\.HK\b')
_BARE_RE = re.compile(r'\b([A-Z][A-Z0-9.=-]{1,11})\b')


def extract_tickers(members, known: set) -> list:
    """Map member headlines + entity phrases to validated platform tickers."""
    found = set()

    def add(sym):
        if sym and sym in known and TICKER_RE.match(sym):
            found.add(sym)

    def alias_scan(text):
        low = ' ' + (text or '').lower() + ' '
        for phrase, cands in TICKER_ALIASES:
            if re.search(r'(?<![a-z0-9])' + re.escape(phrase) +
                         r'(?![a-z0-9])', low):
                for c in cands:
                    if c in known:
                        add(c)
                        break

    for m in members:
        head, ent = m['headline'], m['entity']
        alias_scan(head)
        alias_scan(ent)
        for cs in _CASHTAG_RE.findall(head):
            add(cs.upper())
        for hk in _HKCODE_RE.findall(head):
            add(f'{hk}.HK')
        # bare all-caps tokens already in platform convention (SPY, GC=F,
        # BTC-USD, EURUSD=X, 0700.HK written uppercase in text, ...)
        for tok in _BARE_RE.findall(head):
            if tok not in _CAPS_STOP:
                add(tok)
    return sorted(found)[:12]


# --- impact components (kanban t_1f96bc9b) -----------------------------------
# impact_score is the exact sum of 5 rounded point components (max 100).
# The News tooltip renders these verbatim, so they must sum precisely.
#   coverage       25pts: story breadth      min(members/6, 1)
#   attention      25pts: sustained interest  distinct member hours in the
#                          trailing 24h /6 capped (same member timestamps the
#                          24h attention micro-chart buckets)
#   recency        20pts: freshness           max(0, 1 - age_h/72)
#   keyword_impact 15pts: impact keywords     min(hits/6, 1)
#   llm_impact     15pts: LLM layer           llm_confidence x 15, 0 when null
# BREADTH GATE (kanban t_46609992): a 1-outlet singleton can take ALL 50
# breadth-independent points (recency+keyword+llm) and outrank fragmented
# multi-outlet clusters in the top-6. Singletons are capped at 25 total by
# scaling recency/keyword/llm into the budget left after coverage+attention;
# the scaled components still sum exactly to impact_score (tooltip invariant).
W_COVERAGE, W_ATTENTION, W_RECENCY, W_KEYWORD, W_LLM = 25, 25, 20, 15, 15
SINGLETON_CAP = 25


def impact_components(members, text_blob, age_h, llm_confidence, now) -> dict:
    cov = round(W_COVERAGE * min(len(members) / 6.0, 1.0))
    cutoff = now - timedelta(hours=24)
    hours = {m['dt'].replace(minute=0, second=0, microsecond=0)
             for m in members if m['dt'] and m['dt'] >= cutoff}
    att = round(W_ATTENTION * min(len(hours) / 6.0, 1.0))
    rec = round(W_RECENCY * max(0.0, 1.0 - age_h / 72.0))
    kw = round(W_KEYWORD * min(impact_hits(text_blob) / 6.0, 1.0))
    try:
        llm = round(W_LLM * float(llm_confidence)) if llm_confidence is not None else 0
    except (TypeError, ValueError):
        llm = 0
    if len(members) == 1:
        rest = rec + kw + llm
        budget = max(SINGLETON_CAP - (cov + att), 0)
        if rest > budget:
            scale = budget / rest
            rec = round(rec * scale)
            kw = round(kw * scale)
            llm = budget - (rec + kw)  # exact-sum fixup absorbs rounding
            if llm < 0:                # rounding overflow: bleed into kw/rec
                kw = max(kw + llm, 0)
                llm = 0
                if rec + kw > budget:
                    rec = budget - kw
    return {'attention': att, 'coverage': cov, 'recency': rec,
            'keyword_impact': kw, 'llm_impact': llm}


# --- clustering ---------------------------------------------------------------
# Language scoping (kanban t_0461676c): the reader languages (EN+ZH) share
# one scope; every other language is its own scope. Cross-language merging
# is what built the 112-151-member vi/hi/ar gold-daily mega-blobs —
# multilingual embeddings rate same-genre cross-language dailies at
# 0.70-0.85, inside any threshold that could merge same-event paraphrases.
CORE_LANGS = ('en', 'zh')


def lang_scope(lang) -> str:
    l = (lang or '').lower()
    if not l or l.startswith(CORE_LANGS):
        return 'core'
    return l


# --- GDELT lang mislabel repair (kanban t_2113ec95, issue 2) ------------------
# GDELT labels Indonesian/Turkish (and others) headlines lang='en' (27 'Harga
# Emas' rows in one 48h window), so scoping on the stored label cannot
# isolate the id/tr gold-daily genre blobs — they merge into EN clusters.
# Zero-dependency re-detection at cluster time (fasttext/langid rejected:
# extra model footprint + build risk on the 7GB cron host). Signals, in
# priority order: Unicode script, Vietnamese/Turkish-specific characters,
# stopword lexicons (>=2 word-boundary hits). Domain-based fallback was
# tried and dropped: Turkish outlets carry English wires, which produced
# false positives. Only rows stored as 'en'/NULL are re-detected — GDELT's
# non-en labels were never observed to be wrong, and re-detecting them
# risks moving correctly labelled rows on weaker evidence.
def _has_range(text, lo, hi):
    return any(lo <= ch <= hi for ch in text)


_VI_HORN = set('ơưƠƯ')                    # horn vowels: vi-exclusive
_TR_CHARS = set('ışğİ')                   # near-exclusive to Turkish
# NOTE on vi detection: single 'ă/â/ê/ô' chars are NOT vi signals (Romanian
# uses ă/â, French ê/ô — both produced false positives in the 2026-08-13
# evidence run). vi is detected by tone-stacked precomposed chars
# (U+1EA0-1EF9) or horn vowels, both Vietnamese-exclusive.
_ID_LEX = {'yang', 'dan', 'ini', 'hari', 'harga', 'emas', 'antam', 'naik',
           'turun', 'jadi', 'juta', 'ribu', 'gram', 'cek', 'daftar',
           'rincian', 'terbaru', 'melemah', 'menguat', 'anjlok', 'melonjak',
           'tembus', 'rabu', 'selasa', 'senin', 'kamis', 'jumat', 'sabtu',
           'minggu', 'agustus', 'perdagangan', 'pegadaian', 'perhiasan',
           'buyback', 'logam', 'mulia', 'untuk', 'dengan', 'pada', 'dari',
           'dalam', 'tidak', 'akan', 'kembali', 'lagi', 'saat'}
_TR_LEX = {'bir', 'için', 'ile', 'altın', 'fiyat', 'gram', 'bugün',
           'yükseliş', 'düşüş', 'ağustos', 'güncel', 'çeyrek', 'yatırım',
           'zirve', 'kritik', 'ons', 'gramlık', 'kapalıçarşı'}


def detect_lang_override(headline: str, outlet: str, stored) -> str:
    """Return the effective language for scoping. Re-detects only rows
    stored as 'en'/NULL; everything else trusts the stored label."""
    l = (stored or '').lower()
    if l and not l.startswith('en'):
        return stored
    h = headline or ''
    # Unicode script blocks
    if _has_range(h, '぀', 'ヿ'):
        return 'ja'
    if _has_range(h, '一', '鿿'):
        return 'zh'
    if _has_range(h, '가', '힣'):
        return 'ko'
    if _has_range(h, 'Ѐ', 'ӿ'):
        return 'ru'
    if _has_range(h, '؀', 'ۿ'):
        return 'ar'
    if _has_range(h, 'ऀ', 'ॿ'):
        return 'hi'
    if _has_range(h, '฀', '๿'):
        return 'th'
    if _has_range(h, '֐', '׿'):
        return 'he'
    # Vietnamese: precomposed tone chars (U+1EA0-1EF9) or horn vowels
    if _has_range(h, 'ạ', 'ỹ') or any(c in _VI_HORN for c in h):
        return 'vi'
    # Turkish: near-exclusive characters
    if any(c in _TR_CHARS for c in h):
        return 'tr'
    toks = set(re.findall(r"[a-zà-ÿ]{2,}", h.lower()))
    if len(toks & _ID_LEX) >= 2:
        return 'id'
    if len(toks & _TR_LEX) >= 2:
        return 'tr'
    return stored or 'en'


# Generic live-blog wraps (t_0461676c): residual titles like 'Live updates',
# 'Stock market today' are a GENRE, not an event — CNBC's live blog and
# CNN's live blog are different stories that happen to share a label. They
# are excluded from merging and stand alone as singletons.
_GENERIC_WRAP_RE = re.compile(
    r'\b(live updates?|live blog|markets? today|stock market|market wrap|'
    r'closing bell|morning call|market open|market close)\b', re.I)
_GENERIC_WORDS = {'live', 'update', 'updates', 'blog', 'today', 'wrap',
                  'bell', 'stock', 'stocks', 'market', 'markets', 'open',
                  'close', 'morning', 'call', 'asia', 'asian', 'europe'}


def is_generic_wrap(headline: str) -> bool:
    low = (headline or '').lower()
    if not _GENERIC_WRAP_RE.search(low):
        return False
    toks = set(re.findall(r'[a-z]{3,}', low)) - _GENERIC_WORDS
    return len(toks) <= 1


# City-rate daily genre (kanban t_2113ec95, issue 3): 'Gold prices in
# Pakistan today – Check 24, 22 & 21 karat rates', 'Check rates of 24K, 22K
# gold in Delhi, Mumbai', 'Gold, silver prices see rise in Pakistan - Aug
# 12'. A daily GENRE (per-city retail rate checks), not an event — in the
# small METAL scope they share enough genre tokens ('gold','rise','price')
# to glue gold events, oil items and mining earnings into one blob.
# Isolated as singletons like generic wraps; the id/tr editions are
# additionally re-scoped out of core by detect_lang_override().
_CITY_RATE_GOLD_RE = re.compile(r'\b(gold|silver)\b', re.I)
_CITY_RATE_PRICE_RE = re.compile(r'\b(rates?|prices?)\b', re.I)
_CITY_RATE_GEO_RE = re.compile(
    r'\b(pakistan|india|delhi|mumbai|kolkata|chennai|hyderabad|karachi|'
    r'lahore|karats?|carats?|2[124]\s?k\b|sarafa|\binr\b|city-wise)\b', re.I)


def is_city_rate_check(headline: str) -> bool:
    low = headline or ''
    return bool(_CITY_RATE_GOLD_RE.search(low)
                and _CITY_RATE_PRICE_RE.search(low)
                and _CITY_RATE_GEO_RE.search(low))


# E6 salient-token event merge (t_0461676c). Salient = stemmed lowercase
# alpha token, len>=3, not in the stoplist, with document frequency <= 8%
# across the scope's clusters. Event terms ('record', 'rise', 'down',
# 'gain', 'hormuz', 'rba') stay salient; genre terms do not.
_EVENT_STOP = {
    'stocks', 'stock', 'market', 'markets', 'price', 'prices', 'shares',
    'share', 'today', 'says', 'said', 'amid', 'after', 'over', 'with',
    'from', 'that', 'this', 'will', 'would', 'could', 'about', 'into',
    'than', 'then', 'them', 'they', 'their', 'there', 'here', 'what',
    'when', 'where', 'which', 'while', 'also', 'just', 'more', 'most',
    'some', 'such', 'only', 'very', 'much', 'many', 'been', 'have', 'has',
    'had', 'are', 'was', 'were', 'for', 'and', 'the', 'but', 'not', 'you',
    'all', 'can', 'her', 'his', 'its', 'our', 'out', 'who', 'how', 'new',
    'now', 'day', 'week', 'month', 'year', 'low', 'edge', 'edges', 'near',
    'live', 'update', 'updates', 'blog', 'wrap',
}
E6_MIN_SHARED = 2
E6_MAX_DF = 0.08
E6_MAX_AGE_H = 36
E6_COS_GUARD = 0.45
E6_SIZE_CAP = 40
# Temporal-overlap gate (kanban t_2113ec95, issue 4): a pair merges only
# when its activity windows overlap (younger first_seen no later than older
# last_seen + tolerance). The v1 last-activity-within-36h rule alone let
# multi-day running-wrap genres ('Seoul shares ...' dailies) chain into
# event clusters via shared genre tokens.
E6_OVERLAP_TOL_H = 6
# E6B second pass (kanban t_2113ec95, issue 1): on a one-event news day the
# event's own tokens ('cpi','inflation') exceed the DF cap exactly when they
# matter most — in SMALL scopes (METAL: max_df=2-4); in US-core the 8% cap
# is ~24 and they stay salient. A blanket relaxed-DF pass (25%) was tried
# and rejected on audit evidence: genre tokens ('bitcoin' in CRYPTO) flood
# back in and chain unrelated stories at cos>=0.60. Instead E6B keeps the
# 8% DF cap and exempts ONLY macro-calendar anchor tokens
# (gold.macro_calendar, t_7a646947) on their event day, gated by a higher
# centroid cosine (>= 0.60). NOTE: the residual top-10 CPI split is
# angle-distinct sessions (Asia vs US reaction) whose centroid cosine
# (0.39) sits BELOW observed cross-event pairs (0.46-0.66) — no cluster-
# level gate separates them; feed-layer dedupe handles that (t_2113ec95
# child task).
E6B_COS_GUARD = 0.60
E6B_MIN_SHARED = 2

# Macro-calendar anchor tokens (gold.macro_calendar, kanban t_7a646947):
# event name keyword -> tokens forced salient on/around the event date.
_ANCHOR_MAP = [
    ('cpi', {'cpi', 'inflation'}),
    ('fomc', {'fomc', 'fed'}),
    ('payrolls', {'payrolls', 'jobs', 'nfp'}),
    ('rba', {'rba'}),
    ('boj', {'boj'}),
    ('ecb', {'ecb'}),
    ('pboc', {'pboc'}),
    ('lpr', {'lpr'}),
    ('gdp', {'gdp'}),
    ('ppi', {'ppi'}),
    ('pce', {'pce'}),
]


def macro_anchor_tokens(conn, window_hours: int) -> frozenset:
    """Tokens forced salient in the E6B pass: macro events whose date falls
    inside the fetch window (+-1 day of slack for pre-event positioning
    stories). Non-fatal: any failure returns an empty set."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT event FROM gold.macro_calendar
                   WHERE event_date BETWEEN
                         (NOW() - INTERVAL '1 hour' * %s)::date - 1
                         AND CURRENT_DATE + 1""",
                (window_hours,))
            events = [r[0] for r in cur.fetchall()]
    except Exception:
        conn.rollback()
        return frozenset()
    toks = set()
    for ev in events:
        low = (ev or '').lower()
        for kw, tokens in _ANCHOR_MAP:
            if kw in low:
                toks |= tokens
    return frozenset(toks)


def _stem(t: str) -> str:
    for suf in ('ing', 'es', 's'):
        if len(t) > len(suf) + 3 and t.endswith(suf):
            return t[:-len(suf)]
    return t


def _salient_tokens(text: str) -> set:
    return {_stem(w) for w in re.findall(r'[a-z]{3,}', (text or '').lower())
            } - _EVENT_STOP


def event_merge(items: list, vecs: np.ndarray, clusters: list,
                max_df_frac: float = E6_MAX_DF,
                cos_guard: float = E6_COS_GUARD,
                min_shared: int = E6_MIN_SHARED,
                force_salient: frozenset = frozenset(),
                overlap_tol_h: float = E6_OVERLAP_TOL_H,
                audit: list | None = None) -> list:
    """Union-find merge of cluster pairs (already same cat + lang scope)
    sharing >= min_shared salient tokens (DF <= max_df_frac within the
    scope, or in `force_salient` — macro-calendar anchors), with last
    activity within E6_MAX_AGE_H, OVERLAPPING activity windows (younger
    first_seen <= older last_seen + overlap_tol_h), a title-centroid cosine
    >= cos_guard guard, and a merged size cap of E6_SIZE_CAP. Pair
    candidates are scored on the pre-merge token sets and applied
    most-shared-first."""
    if len(clusters) < 2:
        return clusters
    docs = []
    for cl in clusters:
        toks = set()
        for i in cl:
            toks |= _salient_tokens(
                items[i]['headline'] + ' ' + (items[i].get('entity') or ''))
        docs.append(toks)
    df = {}
    for d in docs:
        for t in d:
            df[t] = df.get(t, 0) + 1
    max_df = max(2, int(max_df_frac * len(clusters)))
    salient = [{t for t in d if df[t] <= max_df or t in force_salient}
               for d in docs]
    first = [min(items[i]['dt'] for i in cl) for cl in clusters]
    last = [max(items[i]['dt'] for i in cl) for cl in clusters]
    cents = []
    for cl in clusters:
        c = vecs[cl].mean(axis=0)
        cents.append(c / (np.linalg.norm(c) or 1.0))
    pairs = []
    for a in range(len(clusters)):
        for b in range(a + 1, len(clusters)):
            shared = salient[a] & salient[b]
            if len(shared) < min_shared:
                continue
            if abs((last[a] - last[b]).total_seconds()) > E6_MAX_AGE_H * 3600:
                continue
            # temporal overlap: the younger cluster must have started no
            # later than the older cluster's last activity (+ tolerance)
            gap = (max(first[a], first[b])
                   - min(last[a], last[b])).total_seconds()
            if gap > overlap_tol_h * 3600:
                continue
            if float(np.dot(cents[a], cents[b])) < cos_guard:
                continue
            pairs.append((len(shared), a, b, sorted(shared),
                          float(np.dot(cents[a], cents[b]))))
    pairs.sort(reverse=True)
    parent = list(range(len(clusters)))
    members_of = {i: list(cl) for i, cl in enumerate(clusters)}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for _n, a, b, shared, cos in pairs:
        ra, rb = find(a), find(b)
        if ra == rb:
            continue
        if len(members_of[ra]) + len(members_of[rb]) > E6_SIZE_CAP:
            continue
        parent[rb] = ra
        members_of[ra] += members_of[rb]
        if audit is not None:
            audit.append({'a': ra, 'b': rb, 'shared': shared, 'cos': cos})
    return [members_of[r] for r in range(len(clusters)) if find(r) == r]


def embed_all(headlines: list, model=None) -> np.ndarray:
    if model is None:
        from fastembed import TextEmbedding
        model = TextEmbedding(model_name=EMBED_MODEL)
    vecs = np.array(list(model.embed(headlines)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


def cluster_items(items: list, vecs: np.ndarray, threshold: float) -> list:
    """Greedy cosine clustering vs cluster mean embedding. Items pre-sorted
    newest first. Returns list of clusters (lists of item indices)."""
    clusters: list[list[int]] = []
    centroids: list[np.ndarray] = []
    for idx in range(len(items)):
        v = vecs[idx]
        best, best_sim = -1, threshold
        for ci, c in enumerate(centroids):
            sim = float(np.dot(v, c))
            if sim >= best_sim:
                best, best_sim = ci, sim
        if best >= 0:
            clusters[best].append(idx)
            c = centroids[best] * (len(clusters[best]) - 1) + v
            centroids[best] = c / np.linalg.norm(c)
        else:
            clusters.append([idx])
            centroids.append(v.copy())
    return clusters


def cluster_scope(items: list, threshold: float, embed_fn,
                  anchors: frozenset = frozenset()) -> list:
    """Full clustering recipe for ONE asset_class scope (v1 t_0461676c, v2
    t_2113ec95): generic-wrap and city-rate-check items stand alone; the
    rest partition by language scope (EN+ZH core vs per-language), greedy
    title-only first pass at `threshold`, then E6 salient-token event merge,
    then the E6B relaxed-DF pass (macro-calendar anchors forced salient,
    higher centroid-cosine guard). Returns clusters of indices into
    `items`."""
    out: list[list[int]] = []
    parts: dict[str, list[int]] = {}
    for i, it in enumerate(items):
        if is_generic_wrap(it['headline']) or is_city_rate_check(it['headline']):
            out.append([i])
        else:
            parts.setdefault(lang_scope(it.get('lang')), []).append(i)
    for scope in sorted(parts):
        idxs = parts[scope]
        sub = [items[i] for i in idxs]
        vecs = embed_fn([it['headline'] for it in sub])
        clusters = cluster_items(sub, vecs, threshold)
        clusters = event_merge(sub, vecs, clusters)
        clusters = event_merge(sub, vecs, clusters,
                               cos_guard=E6B_COS_GUARD,
                               min_shared=E6B_MIN_SHARED,
                               force_salient=anchors)
        out.extend([[idxs[j] for j in cl] for cl in clusters])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--hours', type=int, default=48)
    ap.add_argument('--threshold', type=float, default=SIM_THRESHOLD)
    args = ap.parse_args()

    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute(
            """SELECT id, date, category, entity_name, headline, source, lang, url, summary
               FROM silver.historical_news
               WHERE category = ANY(%s)
                 AND date >= NOW() - INTERVAL '1 hour' * %s
               ORDER BY date DESC, id DESC""",
            (ASSET_CLASSES, args.hours))
        rows = cur.fetchall()
    print(f'fetched {len(rows)} rows (last {args.hours}h)', flush=True)

    # 1. pre-clean: strip '(copy)', drop url-less rows, drop title+outlet
    #    dupes, repair GDELT lang mislabels (t_2113ec95)
    items, seen = [], set()
    dropped_copy = dropped_nourl = dropped_dupe = 0
    lang_fixed = {}
    for rid, dt, cat, ent, head, src, lang, url, summary in rows:
        norm = normalize_headline(head or '')
        if not norm:
            continue
        if norm != (head or '').strip():
            dropped_copy += 1
        if not url:
            dropped_nourl += 1
            continue
        outlet = (src or '').replace('gdelt:', '')
        eff_lang = detect_lang_override(norm, outlet, lang)
        if eff_lang != (lang or 'en'):
            lang_fixed[eff_lang] = lang_fixed.get(eff_lang, 0) + 1
        key = (cat, norm.lower(), outlet.lower())
        if key in seen:
            dropped_dupe += 1
            continue
        seen.add(key)
        items.append({'id': rid, 'dt': dt, 'cat': cat, 'entity': ent or '',
                      'headline': norm, 'outlet': outlet,
                      'lang': eff_lang,
                      'url': url, 'summary': (summary or '').strip()})
    print(f'pre-clean: {len(items)} kept '
          f'(copy-stripped={dropped_copy}, no-url dropped={dropped_nourl}, '
          f'exact dupes dropped={dropped_dupe})', flush=True)
    if lang_fixed:
        print('lang re-detect (stored en -> detected): '
              + ', '.join(f'{k}={v}' for k, v in sorted(lang_fixed.items())),
              flush=True)
    with_summary = sum(1 for it in items if it['summary'])
    print(f'lede coverage: {with_summary}/{len(items)} items have summary '
          f'({100.0 * with_summary / max(len(items), 1):.1f}%)', flush=True)
    if not items:
        print('nothing to cluster', flush=True)
        return 0

    # 2. embed + cluster, scoped by asset_class. Recipe v2 (t_2113ec95):
    #    cluster_scope() isolates generic live-blog wraps AND city-rate
    #    dailies as singletons, partitions the rest by (re-detected)
    #    language scope, greedy title-only first pass at --threshold, E6
    #    event merge with temporal-overlap gate, then the E6B relaxed-DF
    #    pass with macro-calendar anchor tokens. One shared embedding model
    #    across all scopes.
    anchors = macro_anchor_tokens(conn, args.hours)
    print(f'macro-calendar anchors: {sorted(anchors) or "none"}', flush=True)
    from fastembed import TextEmbedding
    model = TextEmbedding(model_name=EMBED_MODEL)

    def embed_fn(headlines):
        return embed_all(headlines, model)

    out_clusters = []
    for cat in ASSET_CLASSES:
        idxs = [i for i, it in enumerate(items) if it['cat'] == cat]
        if not idxs:
            continue
        sub = [items[i] for i in idxs]
        for cl in cluster_scope(sub, args.threshold, embed_fn, anchors):
            out_clusters.append((cat, [idxs[i] for i in cl]))
    print(f'clustered into {len(out_clusters)} stories '
          f'(recipe v2: title-only @ {args.threshold} + E6/E6B event merge '
          f'+ lang re-detect + city-rate isolation)', flush=True)

    # 3. LLM outlook join keys — news_outlook.cluster_key now carries the
    # embedding cluster_id verbatim (extract_clusters.py --source embedding)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT DISTINCT ON (category, cluster_key)
                      category, cluster_key, bias, confidence, rationale
               FROM consumption.news_outlook
               WHERE row_type = 'cluster'
               ORDER BY category, cluster_key, run_date DESC""")
        outlook = {(r[0], r[1]): {'bias': r[2], 'confidence': r[3],
                                  'rationale': r[4]} for r in cur.fetchall()}
        # Known ticker universe for tickers[] validation (t_03bdbbfa):
        # gold.daily_ohlcv symbols UNION currently-held position tickers.
        cur.execute("SELECT DISTINCT ticker FROM gold.daily_ohlcv")
        known_tickers = {r[0] for r in cur.fetchall()}
        try:
            cur.execute("""SELECT DISTINCT ticker
                           FROM consumption.portfolio_positions_current
                           WHERE status = 'ACTIVE'""")
            known_tickers |= {r[0] for r in cur.fetchall()}
        except Exception:
            conn.rollback()
    print(f'ticker universe: {len(known_tickers)} symbols', flush=True)

    # 4. build rows
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    records = []
    canon_best = {}  # lower(canonical) -> index into records; global dedupe
    for cat, member_idxs in out_clusters:
        members = [items[i] for i in member_idxs]
        # canonical: highest-authority outlet; tie -> earliest first_seen
        canonical = min(members,
                        key=lambda m: (outlet_rank(m['outlet']), m['dt']))
        canon_norm = canonical['headline'].lower()

        first_seen = min(m['dt'] for m in members)
        last_seen = max(m['dt'] for m in members)
        outlets = sorted({m['outlet'] for m in members if m['outlet']})
        text_blob = ' '.join(m['headline'] for m in members)
        age_h = (now - last_seen).total_seconds() / 3600.0 if last_seen else 999.0
        tickers = extract_tickers(members, known_tickers)
        # cluster_id = sha1(cat|lower(canonical_headline))[:16]; the outlook
        # layer (extract_clusters.py --source embedding) copies it verbatim
        # into news_outlook.cluster_key, so join on cid directly.
        cid = hashlib.sha1(f"{cat}|{canon_norm}".encode()).hexdigest()[:16]
        llm = outlook.get((cat, cid)) or {}
        comp = impact_components(members, text_blob, age_h,
                                 llm.get('confidence'), now)
        impact_score = sum(comp.values())
        members_json = [{'headline': m['headline'], 'outlet': m['outlet'],
                         'published_at': m['dt'].isoformat(), 'url': m['url'],
                         'lang': m['lang']}
                        for m in sorted(members, key=lambda m: m['dt'],
                                        reverse=True)]
        rec = (
            cid, args.hours, canonical['headline'], len(members), len(outlets),
            first_seen, last_seen, cat, driver_tags(text_blob), tickers,
            llm.get('bias'), llm.get('confidence'), llm.get('rationale'),
            impact_score, json.dumps(comp),
            json.dumps(members_json, ensure_ascii=False))
        # Global canonical-text dedupe (acceptance: no two clusters share the
        # same canonical_headline, case-insensitive). The same GDELT story can
        # be tagged into two scopes (e.g. US+HK); keep the stronger cluster.
        prev_i = canon_best.get(canon_norm)
        if prev_i is None:
            canon_best[canon_norm] = len(records)
            records.append(rec)
        else:
            prev = records[prev_i]
            if (rec[3], rec[13]) > (prev[3], prev[13]):  # story_count, impact
                records[prev_i] = rec

    with conn.cursor() as cur:
        cur.execute('DELETE FROM consumption.news_clusters WHERE window_hours = %s',
                    (args.hours,))
        cur.executemany(
            """INSERT INTO consumption.news_clusters
               (cluster_id, window_hours, canonical_headline, story_count,
                outlet_count, first_seen_utc, last_seen_utc, asset_class,
                driver_tags, tickers, llm_direction, llm_confidence,
                llm_rationale, impact_score, impact_components, members)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            records)
    conn.commit()
    conn.close()
    n_llm = sum(1 for r in records if r[10])
    print(f'✅ wrote {len(records)} clusters ({n_llm} with LLM outlook), '
          f'window={args.hours}h', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
