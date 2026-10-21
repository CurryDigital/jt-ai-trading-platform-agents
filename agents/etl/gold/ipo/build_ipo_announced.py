#!/usr/bin/env python3
"""
Gold: promote active HK IPO filings (A1/PHIP) to gold.hk_ipo_calendar as
pre-subscription placeholder rows (kanban t_59228b1e, 2026-09-05)
================================================================
Reads from: silver.hk_ipo_filings, silver.unified_ipo_calendar
Writes to:  gold.hk_ipo_calendar

Placeholder convention:
  * ticker       = 'A1-<applicant_id>' (MAIN) / 'A1G-<applicant_id>' (GEM)
                   — namespaced so they can never collide with real 'NNNN.HK'
                   tickers and are safe to bulk-delete by prefix.
  * listing_date = NULL, offer_price = NULL; gold.hk_ipo_details gets NO row,
                   so application_start/end stay NULL in /api/hkex/ipos and
                   the frontend stageOf() classifies these as 'announced'
                   (listing TBC, window TBC).
  * stock_name / stock_name_zh / board carried from the filings feed.

Reconciliation (deterministic, no fuzzy matching):
  A placeholder is deleted when its filing is no longer 'active' AND either
    - it lapsed/returned (no stock code), or
    - it listed: the HKEXnews applisted feed gave us the exact stock code
      (silver.hk_ipo_filings.listed_stock_code) AND the real row for that
      ticker exists in silver.unified_ipo_calendar (NLR/AAStocks feeds).
  If the code is known but the real row has not landed yet, the placeholder
  is kept so the IPO does not vanish from the ANNOUNCED stage in the gap.

Idempotent upsert + prefix-scoped delete. Runs in the gold stage of
Pipeline A after gold/ipo/build_ipo_data.py.
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection  # noqa: E402

# Name-suppression guard: a filing that is still 'active' in the HKEXnews
# appindex can already have a REAL calendar row (code assigned, subscription
# open / grey / just listed) — e.g. 2026-09-05: PHIP applicants Medcaptain,
# Longsys, Excelland were still 'active' while 2041/9976/3231.HK sat in the
# pipeline. Without suppression the company shows twice on the IPO tab.
# Match = normalized-name containment vs any recent real row (listed within
# the last 45d or listing in the future); min length 6 guards against
# generic-name false positives.
LEGAL_SUFFIXES = ("co ltd", "co", "ltd", "limited", "inc", "corp",
                  "corporation", "company", "group", "holdings", "b")


def _norm(name):
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower())
    s = re.sub(r"\s+", " ", s).strip()
    parts = s.split()
    while parts and parts[-1] in LEGAL_SUFFIXES:
        parts.pop()
    return " ".join(parts)


def _matches_real(filing_name, real_names):
    f = _norm(filing_name)
    if len(f) < 6:
        return False
    for r in real_names:
        if not r:
            continue
        short, long = (f, r) if len(f) <= len(r) else (r, f)
        if len(short) >= 6 and short in long:
            return True
    return False


def _suppressed_ids(cur):
    """(board, applicant_id) of active filings that duplicate a recent real row."""
    cur.execute("""
        SELECT board, applicant_id, company_name_en
        FROM silver.hk_ipo_filings WHERE status = 'active'""")
    filings = cur.fetchall()
    cur.execute("""
        SELECT DISTINCT stock_name FROM silver.unified_ipo_calendar
        WHERE listing_date >= CURRENT_DATE - 45""")
    real_names = {_norm(r[0]) for r in cur.fetchall()}
    suppressed = set()
    for board, app_id, name in filings:
        if _matches_real(name, real_names):
            suppressed.add((board, app_id))
            print(f"   suppress duplicate: A1{'G' if board == 'GEM' else ''}-{app_id}"
                  f" {name} (matches a recent real calendar row)")
    return suppressed

SQL_UPSERT = """
INSERT INTO gold.hk_ipo_calendar
  (ticker, stock_name, stock_name_zh, listing_date, offer_price, currency,
   board, is_active, updated_at)
SELECT
  CASE WHEN f.board = 'GEM' THEN 'A1G-' ELSE 'A1-' END || f.applicant_id,
  f.company_name_en,
  f.company_name_zh,
  NULL, NULL, 'HKD',
  f.board,
  TRUE, NOW()
FROM silver.hk_ipo_filings f
WHERE f.status = 'active'
  AND NOT (f.board || ':' || f.applicant_id = ANY(%s))
ON CONFLICT (ticker) DO UPDATE SET
  stock_name    = EXCLUDED.stock_name,
  stock_name_zh = COALESCE(EXCLUDED.stock_name_zh, hk_ipo_calendar.stock_name_zh),
  board         = EXCLUDED.board,
  is_active     = TRUE,
  updated_at    = NOW();
"""

# Delete placeholders whose filing left the active set, once the handover is
# safe: lapsed filings drop immediately; listed filings drop only when the
# real calendar row exists in silver (NLR/AAStocks pipeline owns it from there).
SQL_DELETE = """
DELETE FROM gold.hk_ipo_calendar g
USING silver.hk_ipo_filings f
WHERE g.ticker = (CASE WHEN f.board = 'GEM' THEN 'A1G-' ELSE 'A1-' END || f.applicant_id)
  AND f.status <> 'active'
  AND (
    f.listed_stock_code IS NULL
    OR EXISTS (
      SELECT 1 FROM silver.unified_ipo_calendar c
      WHERE c.ticker = ltrim(f.listed_stock_code, '0') || '.HK'
         OR c.ticker = lpad(ltrim(f.listed_stock_code, '0'), 4, '0') || '.HK'
    )
  );
"""

# Safety net: orphan placeholders whose filings row disappeared entirely
# (e.g. silver row manually removed) — drop anything in the A1 namespace that
# no longer maps to a filings row.
SQL_DELETE_ORPHANS = """
DELETE FROM gold.hk_ipo_calendar g
WHERE (g.ticker LIKE 'A1-%' OR g.ticker LIKE 'A1G-%')
  AND NOT EXISTS (
    SELECT 1 FROM silver.hk_ipo_filings f
    WHERE g.ticker = (CASE WHEN f.board = 'GEM' THEN 'A1G-' ELSE 'A1-' END || f.applicant_id)
  );
"""


def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM silver.hk_ipo_filings WHERE status = 'active'")
    active = cur.fetchone()[0]
    if active == 0:
        # An empty active set is suspicious (feed outage) — do NOT wipe all
        # placeholders on a bad read; the freshness registry will flag it.
        print("⚠️  silver.hk_ipo_filings has 0 active rows — skipping gold "
              "placeholder sync (protecting existing rows)")
        cur.close()
        conn.close()
        sys.exit(0)

    suppressed = _suppressed_ids(cur)
    suppressed_tickers = [
        ('A1G-' if b == 'GEM' else 'A1-') + str(a) for b, a in suppressed]

    cur.execute(SQL_UPSERT, ([f"{b}:{a}" for b, a in suppressed],))
    print(f"✅ gold.hk_ipo_calendar placeholders upserted: {cur.rowcount}"
          f" ({len(suppressed)} suppressed as duplicates of recent real rows)")
    # Remove placeholders that became suppressed this run.
    if suppressed_tickers:
        cur.execute(
            "DELETE FROM gold.hk_ipo_calendar WHERE ticker = ANY(%s)",
            (suppressed_tickers,))
        if cur.rowcount:
            print(f"🧹 suppressed placeholders removed: {cur.rowcount}")
    cur.execute(SQL_DELETE)
    print(f"🧹 placeholders handed over/lapsed: {cur.rowcount}")
    cur.execute(SQL_DELETE_ORPHANS)
    if cur.rowcount:
        print(f"🧹 orphan placeholders removed: {cur.rowcount}")
    conn.commit()
    cur.execute(
        "SELECT COUNT(*) FROM gold.hk_ipo_calendar "
        "WHERE ticker LIKE 'A1-%' OR ticker LIKE 'A1G-%'")
    print(f"   announced placeholders now in gold: {cur.fetchone()[0]}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    run()
