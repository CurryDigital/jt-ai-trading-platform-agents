#!/usr/bin/env python3
"""Entity/ticker extraction for silver.historical_news (task t_f7f1c624).

Precision-first design (a wrong ticker is worse than a missing one):
  - category-scoped dictionaries (US/HK/CRYPTO/FX/METAL) — no cross-scope matches
  - company-name matching only for cleaned names >=4 chars, minus a generic stoplist
  - ticker-symbol matching only via strong signals: (EXCH: TICK) parentheses,
    $CASH tags, or standalone ALL-CAPS tokens in the registry (minus stopwords)
  - curated ALIAS_MAP for high-frequency financial entities (bitcoin->BTC-USD, ...)

Sources: gold.asset_registry (ticker,name,asset_class,market) via DB, or the
cached asset_registry.csv (--csv) for reproducible validation.

Usage: from extract_tickers import TickerExtractor
       x = TickerExtractor.from_csv('asset_registry.csv')
       x.extract(headline, category) -> list[str]
"""
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------------- alias map
# Curated, high-frequency aliases. Keys: (scope, lowercase alias). Values: ticker.
ALIAS_MAP = {
    # CRYPTO
    ("CRYPTO", "bitcoin"): "BTC-USD", ("CRYPTO", "btc"): "BTC-USD",
    ("CRYPTO", "ethereum"): "ETH-USD", ("CRYPTO", "ether"): "ETH-USD",
    ("CRYPTO", "eth"): "ETH-USD",
    ("CRYPTO", "solana"): "SOL-USD",
    ("CRYPTO", "xrp"): "XRP-USD", ("CRYPTO", "ripple"): "XRP-USD",
    ("CRYPTO", "dogecoin"): "DOGE-USD", ("CRYPTO", "doge"): "DOGE-USD",
    ("CRYPTO", "cardano"): "ADA-USD", ("CRYPTO", "ada"): "ADA-USD",
    ("CRYPTO", "polkadot"): "DOT-USD",
    ("CRYPTO", "chainlink"): "LINK-USD",
    ("CRYPTO", "litecoin"): "LTC-USD", ("CRYPTO", "ltc"): "LTC-USD",
    ("CRYPTO", "binance coin"): "BNB-USD", ("CRYPTO", "bnb"): "BNB-USD",
    # METAL
    ("METAL", "gold"): "GC=F", ("METAL", "xau"): "GC=F",
    ("METAL", "silver"): "SI=F", ("METAL", "xag"): "SI=F",
    ("METAL", "copper"): "HG=F",
    ("METAL", "platinum"): "PL=F",
    # FX (currency nicknames only inside FX scope; 'dollar' deliberately omitted — ambiguous)
    ("FX", "yen"): "USDJPY=X", ("FX", "japanese yen"): "USDJPY=X",
    ("FX", "euro"): "EURUSD=X",
    ("FX", "pound"): "GBPUSD=X", ("FX", "sterling"): "GBPUSD=X",
    ("FX", "swiss franc"): "USDCHF=X", ("FX", "franc"): "USDCHF=X",
    ("FX", "aussie"): "AUDUSD=X", ("FX", "kiwi"): "NZDUSD=X",
    ("FX", "loonie"): "USDCAD=X",
    # US indices
    ("US", "s&p 500"): "^GSPC", ("US", "s&p"): "^GSPC",
    ("US", "s & p 500"): "^GSPC", ("US", "s & p"): "^GSPC",
    ("US", "nasdaq"): "^IXIC",
    ("US", "dow jones"): "^DJI", ("US", "dow"): "^DJI",
    ("US", "russell 2000"): "^RUT",
    ("US", "vix"): "^VIX",
    # HK
    ("HK", "hang seng bank"): "0011.HK",  # before 'hang seng' -> index
    ("HK", "hang seng"): "^HSI", ("HK", "hsi"): "^HSI",
    ("HK", "alibaba"): "9988.HK", ("HK", "tencent"): "0700.HK",
    ("HK", "xiaomi"): "1810.HK", ("HK", "meituan"): "3690.HK",
    ("HK", "hsbc"): "0005.HK", ("HK", "hkex"): "0388.HK",
    ("HK", "jd.com"): "9618.HK", ("HK", "jd "): "9618.HK",
    ("HK", "aia"): "1299.HK", ("HK", "ping an"): "2318.HK",
}

# Aliases that also apply when the row is scoped elsewhere but the mention is
# unambiguous and the ticker belongs to the row's own dictionary — handled by
# scope restriction, so nothing extra here.

# ------------------------------------------------------------- stoplists
# entity names / dictionary names that must never produce a ticker
GENERIC_STOPLIST = frozenset(
    "fed federal reserve treasury cpi sec doj fomc ecb boj pboc opec imf "
    "wall street forex fx currency currencies crypto cryptocurrency "
    "cryptocurrencies blockchain token tokens etf etfs ipo stocks shares "
    "us stocks us stock hong kong china shares china stocks precious metals "
    "mining stock mining stocks bullion dollar gold silver inflation report".split(" ")
)
# multi-word stoplist entries (checked before tokenization)
GENERIC_PHRASES = frozenset([
    "federal reserve", "wall street", "us stocks", "hong kong", "china shares",
    "china stocks", "precious metals", "mining stock", "mining stocks",
    "inflation report",
])

# ALL-CAPS token stoplist (never treat as ticker symbols)
CAPS_STOPLIST = frozenset(
    "US USA UK EU UN AI IT IPO ETF ETFs CPI GDP PPI FOMC SEC DOJ Fed FX USD EUR "
    "JPY GBP CEO CFO CTO COO IPOs NYSE NASDAQ HKEX FED BOJ ECB ATM ETFs RSS FAQ "
    "AM PM TV PR IR ES OP ED AD BC LLC LLP INC CORP LTD CO NO OK SO ON AN AS AT "
    "BE BY DO GO HE IF IN IS ME MY OF OR OX PI RE TO UP WE FFCTO DHE LDP GIFT "
    "PT TSX ADR APR CEO IMF WTI BIS FHA FBI CIA NATO WHO UN CDC NIH FDA EPA NASA "
    "FBI SEC FTC CFTC OCC FDIC".split()
)

# registry name suffixes to strip when building the name dictionary
_SUFFIX_RE = re.compile(
    r"\b(inc|incorporated|corp|corporation|ltd|limited|llc|llp|lp|plc|sa|se|ag|nv|"
    r"holdings?|group|company|co|class\s+[abc]|cl\s+[abc]|adr|ads|sponsored|"
    r"ordinary shares?|common stock|new|the)\.?$", re.I)

_TICKER_PAREN_RE = re.compile(
    r"\((?:NASDAQ|NYSE|NYSE\s*AMERICAN|AMEX|ARCA|HKEX|HKG|SEHK|TSX|LSE|OTC)[:\s]+([A-Z0-9.\-]+)\)")
_CASHTAG_RE = re.compile(r"\$([A-Z]{1,6})\b")
_CAPS_RE = re.compile(r"\b([A-Z]{2,6})\b")
_WORD_RE = re.compile(r"[a-z0-9&']+")

# Cleaned company names that must never enter the dictionary (generic English
# words that collide with real company names — observed false positives).
NAME_BLOCKLIST = frozenset({"news"})

# Phrases that claim a span but emit NO ticker (longer than the alias they
# contain, so longest-first matching blocks the false positive).
NEGATIVE_PHRASES = {
    "CRYPTO": ["bitcoin cash", "baby bitcoin"],  # BCH not in registry; junk token
    "US": ["s & p / tsx", "s&p / tsx", "s&p/tsx"],  # Canadian index, not ^GSPC
}

# FX pair matcher: EUR/USD, USD / JPY, EUR/YEN (->JPY) etc.
_PAIR_RE = re.compile(r"\b([A-Z]{3})\s*/\s*([A-Z]{3})\b")
_PAIR_CCY_ALIAS = {"YEN": "JPY", "RMB": "CNY", "HKD": "HKD"}

MIN_NAME_LEN = 4


def clean_company_name(name: str) -> str:
    """Normalize a registry company name into a matchable phrase ('' = unusable)."""
    if not name:
        return ""
    n = name.strip().lower()
    n = re.sub(r"[.,'()]", " ", n)
    prev = None
    while prev != n:  # strip suffixes repeatedly ('holdings ltd' etc.)
        prev = n
        n = _SUFFIX_RE.sub("", n).strip()
    n = re.sub(r"\s+", " ", n).strip()
    if len(n) < MIN_NAME_LEN:
        return ""
    if n in GENERIC_PHRASES:
        return ""
    return n


class TickerExtractor:
    def __init__(self, registry_rows):
        """registry_rows: iterable of dicts with ticker,name,asset_class,market."""
        # scope -> {cleaned_name: ticker}
        self.names = {"US": {}, "HK": {}, "CRYPTO": {}, "FX": {}, "METAL": {}}
        # scope -> set of ticker symbols (for paren/cashtag/caps matching)
        self.symbols = {k: {} for k in self.names}  # symbol(upper) -> canonical ticker
        for r in registry_rows:
            t = (r["ticker"] or "").strip()
            if not t:
                continue
            ac = (r.get("asset_class") or "").upper()
            mk = (r.get("market") or "").upper()
            scopes = []
            if ac == "STOCK" and mk == "US":
                scopes = ["US"]
            elif ac == "STOCK" and mk == "HK":
                scopes = ["HK"]
            elif ac == "CRYPTO":
                scopes = ["CRYPTO"]
            elif ac == "FX" or ac == "CURRENCY":
                scopes = ["FX"]
            elif ac == "COMMODITY":
                scopes = ["METAL"]
            elif ac in ("ETF", "INDEX", "VOLATILITY"):
                scopes = ["US"] if mk in ("US", "") else []
                if t == "^HSI" or mk == "HK":
                    scopes = ["HK"]
            for s in scopes:
                self.symbols[s][t.upper()] = t
                # register crypto base codes ('AVAX-USD' -> 'AVAX') so bare
                # ALL-CAPS mentions match; base codes are distinctive
                if ac == "CRYPTO" and t.upper().endswith("-USD"):
                    self.symbols[s][t.upper()[:-4]] = t
                cn = clean_company_name(r.get("name") or "")
                if cn and cn not in NAME_BLOCKLIST and cn not in self.names[s]:
                    self.names[s][cn] = t
        # merge curated aliases (OVERRIDE registry names: curated aliases reflect
        # headline usage — 'Nasdaq' in news means the index ^IXIC, not NDAQ Inc.)
        for (scope, alias), t in ALIAS_MAP.items():
            self.names[scope][alias] = t
        # precompile name patterns per scope, longest first; negative phrases
        # carry ticker=None (claim span, emit nothing)
        self._name_patterns = {}
        for scope, d in self.names.items():
            entries = [(p, d[p]) for p in d]
            for neg in NEGATIVE_PHRASES.get(scope, []):
                entries.append((neg, None))
            entries.sort(key=lambda e: len(e[0]), reverse=True)
            self._name_patterns[scope] = [
                (re.compile(r"\b" + re.escape(p) + r"\b"), t) for p, t in entries
            ]

    @classmethod
    def from_csv(cls, path=None):
        path = path or os.path.join(HERE, "asset_registry.csv")
        with open(path, encoding="utf-8") as f:
            return cls(list(csv.DictReader(f)))

    @classmethod
    def from_db(cls, conn=None):
        """Production path (qr_etl): registry from gold.asset_registry via the
        shared ETL connection (DB_* env, direct RDS, sslmode=require) — NOT the
        research SSH-tunnel DSN. Pass an existing conn to reuse one."""
        own = conn is None
        if own:
            import sys
            _shared = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
            if _shared not in sys.path:
                sys.path.insert(0, _shared)
            from db import get_connection
            conn = get_connection()
        try:
            cur = conn.cursor()
            cur.execute("SELECT ticker, name, asset_class, market FROM gold.asset_registry")
            rows = [{"ticker": t, "name": n, "asset_class": a, "market": m}
                    for t, n, a, m in cur.fetchall()]
        finally:
            if own:
                conn.close()
        return cls(rows)

    def extract(self, headline: str, category: str):
        """Return ordered, deduped list of tickers for a headline."""
        scope = category if category in self.names else None
        if not scope or not headline:
            return []
        from scorer import normalize_headline
        text = normalize_headline(headline)  # fix GDELT spacing first
        low = " " + re.sub(r"\s+", " ", text.lower()) + " "
        found = []  # (pos, ticker)

        # 1) parenthetical exchange ticker: (NASDAQ: ADTX)
        for m in _TICKER_PAREN_RE.finditer(text):
            sym = m.group(1).upper()
            if sym in self.symbols[scope]:
                found.append((m.start(), self.symbols[scope][sym]))

        # 2) cashtags $TSLA
        for m in _CASHTAG_RE.finditer(text):
            sym = m.group(1).upper()
            if sym in self.symbols[scope] and sym not in CAPS_STOPLIST:
                found.append((m.start(), self.symbols[scope][sym]))

        # 3) FX pairs first (strong explicit pattern): EUR/USD, USD / JPY,
        # EUR/YEN. Runs on low.upper() so spans align with `low`.
        claimed = []  # spans already matched, to avoid substring double-hits
        if scope == "FX":
            up = low.upper()
            for m in _PAIR_RE.finditer(up):
                base = _PAIR_CCY_ALIAS.get(m.group(1), m.group(1))
                quote = _PAIR_CCY_ALIAS.get(m.group(2), m.group(2))
                t = f"{base}{quote}=X"
                if t.upper() in self.symbols[scope]:
                    claimed.append(m.span())
                    found.append((m.start(), self.symbols[scope][t.upper()]))

        # 3b) company-name / alias dictionary, longest first (None = negative phrase)
        for pat, ticker in self._name_patterns[scope]:
            for m in pat.finditer(low):
                span = m.span()
                if any(span[0] < e and span[1] > s for s, e in claimed):
                    continue
                claimed.append(span)
                if ticker is not None:
                    found.append((span[0], ticker))

        # 4) standalone ALL-CAPS tokens present in registry symbols
        for m in _CAPS_RE.finditer(text):
            sym = m.group(1)
            if sym in CAPS_STOPLIST:
                continue
            if sym in self.symbols[scope]:
                # skip if this span is inside an already-claimed name match
                pos = m.start()
                if any(s - 1 <= pos < e for s, e in claimed):
                    continue
                found.append((pos, self.symbols[scope][sym]))

        seen, out = set(), []
        for _, t in sorted(found, key=lambda x: x[0]):
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out


if __name__ == "__main__":
    x = TickerExtractor.from_csv()
    for scope in x.names:
        print(scope, "names:", len(x.names[scope]), "symbols:", len(x.symbols[scope]))
    tests = [
        ("Morgan Stanley Becomes Official First US Bank To Launch A Spot Bitcoin ETF", "CRYPTO"),
        ("US Stocks Edge Higher ; CarMax Posts Upbeat Earnings - Aditxt ( NASDAQ : ADTX )", "US"),
        ("Silver Falls More Than 6 % as Precious Metals Retreat After Rally", "METAL"),
        ("Dollar Rallies and Gold Falls as T - note Yields Climb", "FX"),
        ("Alibaba and Xiaomi lead Hong Kong tech rally as Hang Seng jumps", "HK"),
        ("Scotiabank Maintained a Buy Rating on Pan American Silver ( PAAS )", "METAL"),
        ("Wall Street steadies itself as Alphabet pulls tech stocks higher", "US"),
        ("Yen Rises Amid Risk - off Mood", "FX"),
    ]
    for h, c in tests:
        print(f"{c:7s} {x.extract(h, c)}  | {h[:70]}")
