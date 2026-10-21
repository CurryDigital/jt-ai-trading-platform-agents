#!/usr/bin/env python3
"""
build_news_signal_performance.py — LLM news-signal accountability job
(kanban t_03fc7ddb).

Measures whether consumption.news_outlook's llm_direction (bias) actually
predicts forward returns of the story's PRIMARY ticker.

Three phases, idempotent, safe to re-run:

  1. CAPTURE — freeze the latest news_outlook cluster batch into the
     persistent ledger consumption.news_signal_events. news_clusters is
     rebuilt wholesale every 2h, so primary ticker + first_seen_utc must be
     captured the same day or the history is gone. Join order:
       a. exact cluster_key -> news_clusters.cluster_id (latest 48h batch)
       b. headline token-Jaccard >= 0.5 vs canonical_headline, same category
       c. no cluster match -> ticker from affected_assets alias map
     Ticker is only accepted if present in gold.daily_ohlcv.

  2. RETURNS — fill matured forward returns from gold.daily_ohlcv:
       base = first close with date >= anchor date; +1d/+5d = close N
       sessions later. +1h uses bronze.ibkr_historical_bars, which is STALE
       (max 2026-07-03): horizon is marked 'unavailable_stale_source' until
       IBKR bar ingest is refreshed (never synthesized).

  3. AGGREGATE — rebuild consumption.news_signal_performance: rolling 30d/90d
     windows, horizons 1h/1d/5d, segments overall / asset_class /
     confidence_bucket (0-20..80-100 of llm_confidence*100), plus coverage
     rows (segment_type='coverage', pct of captured events with a resolvable
     primary ticker). Serves GET /api/news/signal-performance.

Hit:  sign(forward_return) matches bias (bullish->ret>0, bearish->ret<0;
      ret==0 counts as miss). neutral/mixed are excluded from hit rate but
      counted in coverage.
IC:   Spearman rank corr of signed direction * confidence vs forward return
      over scored (directional, return-ok) events.

Run:  python3 consumption/market/build_news_signal_performance.py
Deps: psycopg2 only (system python3 ok).
"""

from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection  # noqa: E402

HORIZONS = ('1h', '1d', '5d')
WINDOWS = {'30d': 30, '90d': 90}
MIN_IC_N = 3            # Spearman needs >= 3 pairs to be meaningful
MIN_SAMPLE = 30         # frontend greys out n < 30; used for status flag

# --- headline tokenisation (matches build_news_clusters.cluster_key tokens) --
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "as", "at", "for",
    "with", "by", "from", "is", "are", "was", "were", "after", "amid", "over",
    "its", "it", "this", "that", "says", "say", "new", "video", "watch",
    "market", "markets", "stocks", "stock", "shares", "prices", "price",
    "today", "week", "day", "ago", "vs", "per", "cent",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CJK_RE = re.compile(r"[一-鿿]")


def news_tokens(headline: str) -> set:
    h = (headline or "").lower()
    toks = {t for t in _TOKEN_RE.findall(h) if t not in _STOPWORDS and len(t) > 1}
    cjk = _CJK_RE.findall(h)
    for i in range(0, max(0, len(cjk) - 1)):
        toks.add("".join(cjk[i:i + 2]))
    return toks


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# --- affected_assets alias map (LLM asset names -> gold.daily_ohlcv tickers).
# Only candidates validated against the daily_ohlcv universe are used.
ASSET_ALIASES = {
    'HSI': ['^HSI'], 'HSTECH': ['^HSTECH'], 'SPX': ['SPY'],
    'XAUUSD': ['GC=F', 'GLD'], 'XAGUSD': ['SI=F', 'SLV'],
    'CL': ['CL=F', 'USO'], 'BRENT': ['CL=F'],
    'GOLD': ['GC=F', 'GLD'], 'SILVER': ['SI=F', 'SLV'],
    'BTC': ['BTC-USD'], 'ETH': ['ETH-USD'], 'SOL': ['SOL-USD'],
    'XRP': ['XRP-USD'], 'DOGE': ['DOGE-USD'],
    'DXY': [],          # no dollar-index series in daily_ohlcv -> unresolved
    'VIX': [],
}
BUCKETS = ['0-20', '20-40', '40-60', '60-80', '80-100']


def conf_bucket(conf) -> str | None:
    if conf is None:
        return None
    pct = min(99.999, max(0.0, float(conf) * 100.0))
    lo = int(pct // 20) * 20
    return f"{lo}-{lo + 20}"


def spearman(pairs: list[tuple[float, float]]) -> float | None:
    """Spearman rank correlation with average ranks for ties."""
    n = len(pairs)
    if n < MIN_IC_N:
        return None

    def ranks(vals):
        order = sorted(range(n), key=lambda i: vals[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and vals[order[j + 1]] == vals[order[i]]:
                j += 1
            avg = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    xs = ranks([p[0] for p in pairs])
    ys = ranks([p[1] for p in pairs])
    mx = sum(xs) / n
    my = sum(ys) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    vx = sum((a - mx) ** 2 for a in xs)
    vy = sum((b - my) ** 2 for b in ys)
    if vx == 0 or vy == 0:
        return None
    return cov / (vx ** 0.5 * vy ** 0.5)


# -----------------------------------------------------------------------------

def load_daily_universe(cur) -> set:
    cur.execute("SELECT DISTINCT ticker FROM gold.daily_ohlcv")
    return {r[0] for r in cur.fetchall()}


def resolve_alias_ticker(assets, universe: set) -> str | None:
    for raw in (assets or []):
        a = str(raw).strip().upper()
        if not a:
            continue
        if a in universe:
            return a
        for cand in ASSET_ALIASES.get(a, []):
            if cand in universe:
                return cand
    return None


def capture_events(cur, universe: set) -> dict:
    """Freeze latest news_outlook cluster batch into the events ledger."""
    cur.execute("""
        SELECT run_date, cluster_key, category, headline, bias, confidence,
               horizon, affected_assets, source_latest
        FROM consumption.news_outlook
        WHERE row_type = 'cluster'
          AND run_date = (SELECT max(run_date) FROM consumption.news_outlook
                          WHERE row_type = 'cluster')
    """)
    rows = cur.fetchall()
    if not rows:
        return {'captured': 0, 'exact': 0, 'jaccard': 0, 'no_match': 0}

    cur.execute("""
        SELECT cluster_id, canonical_headline, tickers, first_seen_utc,
               asset_class
        FROM consumption.news_clusters
        WHERE window_hours = 48
          AND computed_at = (SELECT max(computed_at)
                             FROM consumption.news_clusters
                             WHERE window_hours = 48)
    """)
    clusters = cur.fetchall()
    by_key = {}
    by_class = {}
    for cid, head, tickers, first_seen, aclass in clusters:
        toks = news_tokens(head)
        by_key[cid] = (cid, head, tickers, first_seen, aclass)
        by_class.setdefault(aclass, []).append((cid, toks, tickers, first_seen))

    stats = {'captured': 0, 'exact': 0, 'jaccard': 0, 'no_match': 0}
    for (run_date, ckey, cat, headline, bias, conf, horizon,
         assets, source_latest) in rows:
        primary, tick_src = None, 'none'
        cid_match, match_kind = None, 'none'
        first_seen, anchor_src = None, 'run_date'

        hit = by_key.get(ckey)
        if hit:
            cid_match, match_kind = hit[0], 'exact_key'
            stats['exact'] += 1
            tickers, first_seen = hit[2], hit[3]
        else:
            # fallback: token-Jaccard vs canonical headlines, same category
            q = news_tokens(headline)
            best, best_score = None, 0.0
            for cid, toks, tickers, fs in by_class.get(cat, []):
                s = jaccard(q, toks)
                if s > best_score:
                    best, best_score = (cid, tickers, fs), s
            if best and best_score >= 0.5:
                cid_match, match_kind = best[0], 'headline_jaccard'
                stats['jaccard'] += 1
                tickers, first_seen = best[1], best[2]
            else:
                stats['no_match'] += 1
                tickers = []

        # primary ticker: cluster tickers[0] validated against universe,
        # else affected_assets aliases
        for t in (tickers or []):
            if t in universe:
                primary, tick_src = t, 'cluster_tickers'
                break
        if primary is None:
            t = resolve_alias_ticker(assets, universe)
            if t:
                primary, tick_src = t, 'affected_assets'

        if first_seen:
            anchor_src = 'cluster_first_seen'
        elif source_latest:
            first_seen, anchor_src = source_latest.replace(tzinfo=None), 'source_latest'

        cur.execute("""
            INSERT INTO consumption.news_signal_events
              (run_date, cluster_key, category, headline, bias, confidence,
               horizon, primary_ticker, ticker_source, cluster_id,
               cluster_match, first_seen_utc, anchor_source, ret_1h_status,
               ret_1d_status, ret_5d_status)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'pending','pending','pending')
            ON CONFLICT (run_date, cluster_key) DO UPDATE SET
              headline       = EXCLUDED.headline,
              bias           = EXCLUDED.bias,
              confidence     = EXCLUDED.confidence,
              horizon        = EXCLUDED.horizon,
              -- only upgrade resolution fields when we actually learned more
              primary_ticker = COALESCE(consumption.news_signal_events.primary_ticker,
                                        EXCLUDED.primary_ticker),
              ticker_source  = CASE
                    WHEN consumption.news_signal_events.primary_ticker IS NOT NULL
                         THEN consumption.news_signal_events.ticker_source
                    ELSE EXCLUDED.ticker_source END,
              cluster_id     = COALESCE(consumption.news_signal_events.cluster_id,
                                        EXCLUDED.cluster_id),
              cluster_match  = CASE
                    WHEN consumption.news_signal_events.cluster_id IS NOT NULL
                         THEN consumption.news_signal_events.cluster_match
                    ELSE EXCLUDED.cluster_match END,
              first_seen_utc = COALESCE(consumption.news_signal_events.first_seen_utc,
                                        EXCLUDED.first_seen_utc),
              anchor_source  = CASE
                    WHEN consumption.news_signal_events.first_seen_utc IS NOT NULL
                         THEN consumption.news_signal_events.anchor_source
                    ELSE EXCLUDED.anchor_source END
        """, (run_date, ckey, cat, headline, bias, conf, horizon,
              primary, tick_src, cid_match, match_kind, first_seen, anchor_src))
        stats['captured'] += 1
    return stats


def update_returns(cur) -> dict:
    """Fill matured forward returns from gold.daily_ohlcv; mark 1h stale."""
    stats = {'ret_1d': 0, 'ret_5d': 0, 'h_stale': 0, 'no_price': 0}

    # +1h: bronze.ibkr_historical_bars staleness gate (never synthesize).
    cur.execute("SELECT max(bar_time) FROM bronze.ibkr_historical_bars")
    bars_max = cur.fetchone()[0]
    bars_stale = (bars_max is None or
                  bars_max.replace(tzinfo=None)
                  < datetime.now() - timedelta(days=7))
    if bars_stale:
        cur.execute("""
            UPDATE consumption.news_signal_events
            SET ret_1h_status = 'unavailable_stale_source'
            WHERE ret_1h_status = 'pending'
        """)
        stats['h_stale'] = cur.rowcount
    # (when bars are fresh again, intraday +1h computation goes here)

    # no-ticker events: terminal status
    cur.execute("""
        UPDATE consumption.news_signal_events
        SET ret_1d_status='no_ticker', ret_5d_status='no_ticker',
            ret_1h_status=CASE WHEN ret_1h_status='pending' THEN 'no_ticker'
                               ELSE ret_1h_status END
        WHERE primary_ticker IS NULL
          AND (ret_1d_status='pending' OR ret_5d_status='pending')
    """)

    # pending daily returns, oldest first
    cur.execute("""
        SELECT run_date, cluster_key, primary_ticker, first_seen_utc,
               ret_1d_status, ret_5d_status
        FROM consumption.news_signal_events
        WHERE primary_ticker IS NOT NULL
          AND (ret_1d_status='pending' OR ret_5d_status='pending')
    """)
    pend = cur.fetchall()
    for run_date, ckey, ticker, anchor, s1, s5 in pend:
        anchor_d = (anchor or datetime.combine(run_date, datetime.min.time())).date()
        cur.execute("""
            SELECT date, close FROM gold.daily_ohlcv
            WHERE ticker = %s AND date >= %s
            ORDER BY date ASC LIMIT 8
        """, (ticker, anchor_d))
        rows = cur.fetchall()
        if not rows:
            cur.execute("""
                UPDATE consumption.news_signal_events
                SET ret_1d_status='no_price_data', ret_5d_status='no_price_data',
                    returns_computed_at=NOW()
                WHERE run_date=%s AND cluster_key=%s
            """, (run_date, ckey))
            stats['no_price'] += 1
            continue
        base_date, base_close = rows[0][0], float(rows[0][1])
        closes = [float(r[1]) for r in rows]
        r1 = closes[1] / base_close - 1.0 if len(closes) > 1 else None
        r5 = closes[5] / base_close - 1.0 if len(closes) > 5 else None
        cur.execute("""
            UPDATE consumption.news_signal_events
            SET base_close=%s, base_close_date=%s,
                ret_1d=COALESCE(%s, ret_1d),
                ret_1d_status=CASE WHEN %s THEN 'ok' ELSE ret_1d_status END,
                ret_5d=COALESCE(%s, ret_5d),
                ret_5d_status=CASE WHEN %s THEN 'ok' ELSE ret_5d_status END,
                returns_computed_at=NOW()
            WHERE run_date=%s AND cluster_key=%s
        """, (base_close, base_date, r1, r1 is not None,
              r5, r5 is not None, run_date, ckey))
        if r1 is not None and s1 == 'pending':
            stats['ret_1d'] += 1
        if r5 is not None and s5 == 'pending':
            stats['ret_5d'] += 1
    return stats


def segment_rows(events, horizon, window_label, days):
    """Build aggregate rows for one (horizon, window) over event dicts."""
    today = date.today()
    start = today - timedelta(days=days)
    in_win = [e for e in events
              if e['anchor_date'] and start <= e['anchor_date'] <= today]
    ret_key, st_key = f'ret_{horizon}', f'ret_{horizon}_status'

    out = []
    # coverage row: % of captured events with a resolvable primary ticker
    n_clusters = len(in_win)
    n_resolved = sum(1 for e in in_win if e['ticker'])
    cov_pct = (n_resolved / n_clusters) if n_clusters else None
    out.append({
        'horizon': horizon, 'window': window_label,
        'segment_type': 'coverage', 'segment_value': 'all',
        'hit_rate': None, 'mean_return': None, 'ic': None,
        'coverage_pct': cov_pct, 'sample_size': n_clusters,
        'range': (start, today),
    })

    def scored(filt):
        return [e for e in in_win
                if e['bias'] in ('bullish', 'bearish')
                and e[st_key] == 'ok' and e[ret_key] is not None and filt(e)]

    def agg(label_type, label_val, evs):
        if not evs:
            return None
        hits = sum(1 for e in evs
                   if (e['bias'] == 'bullish') == (e[ret_key] > 0))
        hit_rate = hits / len(evs)
        mean_ret = sum(e[ret_key] for e in evs) / len(evs)
        pairs = [(((1.0 if e['bias'] == 'bullish' else -1.0)
                   * float(e['confidence'] or 0.5)), e[ret_key])
                 for e in evs]
        ic = spearman(pairs)
        return {
            'horizon': horizon, 'window': window_label,
            'segment_type': label_type, 'segment_value': label_val,
            'hit_rate': round(hit_rate, 4),
            'mean_return': round(mean_ret, 5),
            'ic': round(ic, 4) if ic is not None else None,
            'coverage_pct': None, 'sample_size': len(evs),
            'range': (start, today),
        }

    r = agg('overall', 'all', scored(lambda e: True))
    if r:
        out.append(r)
    for ac in sorted({e['category'] for e in in_win}):
        r = agg('asset_class', ac, scored(lambda e, a=ac: e['category'] == a))
        if r:
            out.append(r)
    for b in BUCKETS:
        r = agg('confidence_bucket', b,
                scored(lambda e, bb=b: conf_bucket(e['confidence']) == bb))
        if r:
            out.append(r)
    return out


def rebuild_performance(cur) -> dict:
    cur.execute("""
        SELECT category, bias, confidence, primary_ticker,
               COALESCE(first_seen_utc::date, run_date) AS anchor_date,
               ret_1h, ret_1h_status, ret_1d, ret_1d_status,
               ret_5d, ret_5d_status
        FROM consumption.news_signal_events
    """)
    events = [{
        'category': r[0], 'bias': r[1], 'confidence': r[2], 'ticker': r[3],
        'anchor_date': r[4],
        'ret_1h': float(r[5]) if r[5] is not None else None, 'ret_1h_status': r[6],
        'ret_1d': float(r[7]) if r[7] is not None else None, 'ret_1d_status': r[8],
        'ret_5d': float(r[9]) if r[9] is not None else None, 'ret_5d_status': r[10],
    } for r in cur.fetchall()]

    cur.execute("DELETE FROM consumption.news_signal_performance")
    n = 0
    for wl, days in WINDOWS.items():
        for hz in HORIZONS:
            for row in segment_rows(events, hz, wl, days):
                cur.execute("""
                    INSERT INTO consumption.news_signal_performance
                      (horizon, "window", segment_type, segment_value, hit_rate,
                       mean_return, information_coefficient, coverage_pct,
                       sample_size, computed_for_window, computed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                """, (row['horizon'], row['window'], row['segment_type'],
                      row['segment_value'], row['hit_rate'], row['mean_return'],
                      row['ic'], row['coverage_pct'], row['sample_size'],
                      f"[{row['range'][0]},{row['range'][1]}]"))
                n += 1
    return {'perf_rows': n, 'events_total': len(events)}


def main():
    conn = get_connection()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            universe = load_daily_universe(cur)
            cap = capture_events(cur, universe)
            ret = update_returns(cur)
            agg = rebuild_performance(cur)
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    print(f"[capture] {cap}")
    print(f"[returns] {ret}")
    print(f"[aggregate] {agg}")
    print("OK")


if __name__ == '__main__':
    main()
