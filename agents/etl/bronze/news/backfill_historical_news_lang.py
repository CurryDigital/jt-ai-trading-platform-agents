#!/usr/bin/env python3
"""
backfill_historical_news_lang.py — one-off/rerunnable lang backfill for
silver.historical_news (kanban t_69e09f53).

Fills `lang` (ISO 639-1) on rows where it is NULL using the Unicode-script
heuristic from shared/scripts/news_scopes.py (detect_lang). Latin-script
headlines resolve to 'en' — fr/de/es/vi are indistinguishable at script
level, which the task spec accepts.

Idempotent: only touches lang IS NULL rows. Chunked + committed per chunk so
a kill mid-run loses at most one chunk.

Usage:
  python bronze/news/backfill_historical_news_lang.py [--chunk 5000]
"""

from __future__ import annotations

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection          # noqa: E402
from news_scopes import detect_lang    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--chunk', type=int, default=5000)
    args = ap.parse_args()

    conn = get_connection()
    total = 0
    try:
        while True:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT id, headline FROM silver.historical_news '
                    'WHERE lang IS NULL ORDER BY id LIMIT %s', (args.chunk,))
                rows = cur.fetchall()
                if not rows:
                    break
                updates = [(detect_lang(h) or 'en', i) for i, h in rows]
                cur.executemany(
                    'UPDATE silver.historical_news SET lang = %s '
                    'WHERE id = %s', updates)
                n = len(updates)
            conn.commit()
            total += n
            print(f'  backfilled {total} rows (+{n})', flush=True)
        with conn.cursor() as cur:
            cur.execute('SELECT lang, count(*) FROM silver.historical_news '
                        'GROUP BY lang ORDER BY 2 DESC')
            dist = cur.fetchall()
            cur.execute('SELECT count(*) FROM silver.historical_news '
                        'WHERE lang IS NULL')
            nulls = cur.fetchone()[0]
    finally:
        conn.close()

    print(f'\n✅ lang backfill done: {total} rows updated, NULL remaining: {nulls}')
    print('  distribution:')
    for lang, n in dist:
        print(f'    {lang or "NULL":<6} {n}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
