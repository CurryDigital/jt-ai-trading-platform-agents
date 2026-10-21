#!/usr/bin/env python3
"""
build_news_sentiment_daily.py — gold layer for pipeline C.

Two phases:
  1. SCORE — every silver.news_items row with sent_score IS NULL gets a
     compound sentiment score in [-1, +1] (VADER + finance lexicon overlay,
     scorer tag 'lexicon-vader1'), a bull/bear/neu label and a risk-keyword
     hit count. Scorer is deliberately swappable: a future LLM batch scorer
     writes the same columns with scorer='llm-*' and re-scores by NULLing
     sent_score for the window.

     DECISION (2026-08-07, frame doc open-question #1): lexicon, not LLM
     batch. No LLM API key is provisioned for ETL cron use — the only
     credentials on this box are the agent's interactive provider keys
     (kimi-coding / copilot credential pool), which are unsuitable and
     unsustainable inside a headless daily cron. Lexicon is free,
     deterministic and reproducible over the 24-month backfill. Swap path
     documented in agents/etl/docs/news_pipeline_c_sources.md.

  2. AGGREGATE — per (date, scope) upserts into gold.news_sentiment_daily:
       sent_mean           avg of per-item compound scores (item = unit of
                           volume, so the mean IS the volume weighting)
       sent_dispersion     population stddev across items (NULL if <2 items)
       news_volume         item count
       volume_z            news_volume z-score vs trailing 60d of this table
                           (NULL until >=20 prior observations)
       risk_keyword_hits   sum of per-item risk keyword hits
       high_severity_event 1 when gold.macro_event_flags.severity='heavy'
                           that date (FOMC/CPI/NFP-class days)

     Default window: trailing 3 days (re-aggregates to catch late arrivals).
     --backfill aggregates every date present in silver.news_items.

Freshness contract: mark_source_refreshed('news_pipeline_c',
expected_max_staleness_hours=30) on success; error path on failure. Pipeline C
is NOT in pipeline B's dependency chain — B downweights news features when
this row is stale.

Cron: pipeline C wrapper, after silver/news/clean_news.py.
Standalone: python agents/etl/gold/market/build_news_sentiment_daily.py [--days 3 | --backfill]
"""

from __future__ import annotations

import argparse
import os
import statistics
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection                  # noqa: E402
from freshness import freshness_guard          # noqa: E402
from news_scopes import SCOPES, risk_hit_count  # noqa: E402

SCORER = 'lexicon-vader1'

# Finance overlay on top of VADER's base lexicon (single tokens only).
FINANCE_LEXICON = {
    'beats': 2.0, 'beat': 1.4, 'misses': -2.0, 'miss': -1.2,
    'upgrade': 2.0, 'upgrades': 2.0, 'upgraded': 2.0,
    'downgrade': -2.0, 'downgrades': -2.0, 'downgraded': -2.0,
    'surge': 2.2, 'surges': 2.2, 'surged': 2.2, 'soar': 2.4, 'soars': 2.4,
    'plunge': -2.8, 'plunges': -2.8, 'plunged': -2.8, 'plummet': -2.8,
    'plummets': -2.8, 'rally': 2.0, 'rallies': 2.0, 'selloff': -2.4,
    'bankruptcy': -3.0, 'bankrupt': -3.0, 'default': -2.6, 'bailout': -2.2,
    'recession': -2.4, 'layoffs': -2.2, 'profit': 1.6, 'profits': 1.6,
    'outperform': 1.8, 'underperform': -1.8, 'bullish': 2.2, 'bearish': -2.2,
    'crash': -3.0, 'crashes': -3.0, 'tariff': -1.2, 'tariffs': -1.2,
    'sanctions': -1.8, 'war': -2.2, 'ceasefire': 1.8, 'stimulus': 1.6,
    'hawkish': -1.4, 'dovish': 1.2, 'slump': -2.2, 'slumps': -2.2,
    'rebound': 1.8, 'rebounds': 1.8, 'tumbles': -2.4, 'tumble': -2.4,
    'jumps': 1.8, 'jump': 1.8, 'gains': 1.4, 'gain': 1.2, 'losses': -1.4,
    'falls': -1.2, 'fall': -1.0, 'rises': 1.2, 'rise': 1.0, 'drops': -1.4,
    'drop': -1.2, 'climbs': 1.4, 'climb': 1.2, 'sinks': -1.8, 'sink': -1.6,
}


def _analyzer():
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    a = SentimentIntensityAnalyzer()
    a.lexicon.update(FINANCE_LEXICON)
    return a


def score_unscored(conn, batch: int = 20000) -> int:
    analyzer = _analyzer()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, headline, COALESCE(body, '') FROM silver.news_items "
            "WHERE sent_score IS NULL ORDER BY date DESC LIMIT %s", (batch,))
        rows = cur.fetchall()
        for _id, headline, body in rows:
            compound = analyzer.polarity_scores(headline or '')['compound']
            label = 'bull' if compound >= 0.05 else ('bear' if compound <= -0.05 else 'neu')
            cur.execute(
                "UPDATE silver.news_items SET sent_score=%s, sent_label=%s, "
                "risk_hits=%s, scorer=%s, scored_at=NOW() WHERE id=%s",
                (round(compound, 4), label, risk_hit_count(headline, body),
                 SCORER, _id))
    conn.commit()
    print(f'  scored {len(rows)} items (scorer={SCORER})')
    return len(rows)


AGG_SQL = """
SELECT COUNT(*),
       AVG(sent_score),
       STDDEV_POP(sent_score),
       COALESCE(SUM(risk_hits), 0),
       COUNT(sent_score)
FROM silver.news_items
WHERE date = %s AND scopes @> ARRAY[%s]::text[]
"""

UPSERT_SQL = """
INSERT INTO gold.news_sentiment_daily
    (date, scope, sent_mean, sent_dispersion, news_volume, volume_z,
     risk_keyword_hits, high_severity_event, scored_items, scorer, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
ON CONFLICT (date, scope) DO UPDATE SET
    sent_mean           = EXCLUDED.sent_mean,
    sent_dispersion     = EXCLUDED.sent_dispersion,
    news_volume         = EXCLUDED.news_volume,
    volume_z            = EXCLUDED.volume_z,
    risk_keyword_hits   = EXCLUDED.risk_keyword_hits,
    high_severity_event = EXCLUDED.high_severity_event,
    scored_items        = EXCLUDED.scored_items,
    scorer              = EXCLUDED.scorer,
    updated_at          = NOW();
"""

HIST_VOL_SQL = """
SELECT news_volume FROM gold.news_sentiment_daily
WHERE scope = %s AND date < %s
ORDER BY date DESC LIMIT 60;
"""

SEVERITY_SQL = "SELECT severity FROM gold.macro_event_flags WHERE date = %s;"


def aggregate(conn, dates: list[date]) -> int:
    written = 0
    with conn.cursor() as cur:
        for d in dates:
            cur.execute(SEVERITY_SQL, (d,))
            row = cur.fetchone()
            high_sev = 1 if (row and row[0] == 'heavy') else 0
            for scope in SCOPES:
                cur.execute(AGG_SQL, (d, scope))
                vol, mean, disp, risk, scored = cur.fetchone()
                volume_z = None
                if vol:
                    cur.execute(HIST_VOL_SQL, (scope, d))
                    hist = [r[0] for r in cur.fetchall() if r[0] is not None]
                    if len(hist) >= 20:
                        sd = statistics.pstdev(hist)
                        if sd > 0:
                            volume_z = round((vol - statistics.mean(hist)) / sd, 4)
                cur.execute(UPSERT_SQL, (
                    d, scope,
                    round(float(mean), 4) if mean is not None else None,
                    round(float(disp), 4) if disp is not None else None,
                    vol, volume_z, int(risk or 0), high_sev, int(scored or 0),
                    SCORER,
                ))
                written += cur.rowcount
    conn.commit()
    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=3)
    ap.add_argument('--backfill', action='store_true',
                    help='aggregate every date present in silver.news_items')
    args = ap.parse_args()

    with freshness_guard(source='news_pipeline_c',
                         expected_max_staleness_hours=30):
        conn = get_connection()
        try:
            score_unscored(conn)

            if args.backfill:
                with conn.cursor() as cur:
                    cur.execute("SELECT DISTINCT date FROM silver.news_items ORDER BY 1")
                    dates = [r[0] for r in cur.fetchall()]
            else:
                today = date.today()
                dates = [today - timedelta(days=i) for i in range(args.days)]

            written = aggregate(conn, dates)

            # freshness: latest date we actually aggregated
            max_date = max(dates) if dates else None
            from freshness import mark_source_refreshed
            mark_source_refreshed(conn, source='news_pipeline_c', max_date=max_date,
                                  expected_max_staleness_hours=30)
        finally:
            conn.close()

        print(f'✅ gold.news_sentiment_daily — {written} (date, scope) rows upserted '
              f'across {len(dates)} dates x {len(SCOPES)} scopes')
    return 0


if __name__ == '__main__':
    sys.exit(main())
