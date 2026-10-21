#!/usr/bin/env python3
"""
Silver: daily HK IPO calendar refresh (kanban 5711f0bb, 2026-08-31)
==================================================================
Purpose: keep silver.unified_ipo_calendar current so event-driven strategies
(hk_ipo_postlisting_drift_p1) detect NEW qualifying IPOs (retail
oversubscription 100-500x) without a manual backfill.

Source: AAStocks Listed-IPO table
  http://www.aastocks.com/en/stocks/market/ipo/listedipo.aspx?s=3&o=0&page=N
  (15 pages, ~3y of history, includes upcoming listings; 1.5s polite delay)
Verified working per skill etl-hk-ipo-data-sources (2026-08-30).

Flow per run:
  1. bronze.aastocks_ipo_listed_raw   - upsert raw rows (PK symbol)
  2. silver.unified_ipo_calendar      - upsert on (ticker, listing_date):
       * new IPOs inserted (oversubscription_retail may be NULL until
         allotment results publish; refreshed on later runs)
       * existing rows get oversubscription_retail / lot_size /
         one_lot_success_pct filled when AAStocks has a value and silver
         is NULL, or corrected when the value differs (AAStocks is the
         canonical oversub source per the 2026-08-30 backfill)
  3. gold.asset_registry              - auto-onboard newly LISTED tickers
       (listing_date <= today) as STOCK/HK/1d/active so the daily bronze
       yfinance stage (universe = active registry tickers) picks up prices
       and gold.hk_ipo_* builds downstream see the name/sector.
  4. gold.source_freshness            - mark_source_refreshed('aastocks_ipo')

Does NOT fetch prices directly (Pipeline A bronze yfinance stage owns that)
and does NOT write gold.hk_ipo_* (gold/ipo/build_ipo_data.py stage owns that;
already in pipeline_manifest.json).

Idempotent. Row errors tolerated up to 5, then non-zero exit.
"""
import os
import re
import sys
import time
from datetime import date, datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection  # noqa: E402

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"missing package: {e.name} — etl-venv needs requests+beautifulsoup4")
    sys.exit(1)

BASE_URL = ("http://www.aastocks.com/en/stocks/market/ipo/listedipo.aspx"
            "?s=3&o=0&page={page}")
TC_BASE_URL = ("http://www.aastocks.com/tc/stocks/market/ipo/listedipo.aspx"
               "?s=3&o=0&page={page}")
N_PAGES = 15
DELAY_S = 1.5
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
CODE_RE = re.compile(r"(\d{5})\.HK")
CJK_RE = re.compile(r"[一-鿿]")
# trailing status annotations AAStocks appends to the name cell
NAME_JUNK_RE = re.compile(
    r"(Sink Below Listing Price|Above Listing Price|At Listing Price|"
    r"Newly Listed|Listing Today)$")
TC_NAME_JUNK_RE = re.compile(
    r"(低於上市價|高於上市價|與上市價相同|新上市|今日上市)$")

_row_errors = 0


def _num(s):
    if s is None:
        return None
    s = s.replace(",", "").replace("%", "").strip()
    if s in ("", "N/A", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_page(html):
    """Return list of dicts for data rows of the listed-IPO table."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="dataTable")
    if table is None:
        return []
    out = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) < 13:
            continue
        m = CODE_RE.search(cells[1])
        if not m:
            continue
        symbol = m.group(1)                       # '03223'
        name = cells[1][:m.start()]
        name = NAME_JUNK_RE.sub("", name).strip() or None
        # 2026-09-02 (t_437922f4): pre-listing rows sometimes render an
        # internal AAStocks assign code ('AACCOAL@EC0805A') as the name.
        if name and "@" in name:
            name = None
        try:
            listing = datetime.strptime(cells[2], "%Y/%m/%d").date()
        except ValueError:
            continue
        lot = _num(cells[3])
        # AAStocks symbol is 5-digit zero-padded ('03223'); DB convention is
        # 4-digit ('3223.HK', leading zero kept for codes < 1000: '0600.HK').
        ticker4 = symbol[1:] if symbol.startswith("0") else symbol
        out.append({
            "symbol": symbol,
            "ticker": ticker4 + ".HK",            # '03223' -> '3223.HK'
            "stock_name": name,
            "listing_date": listing,
            "lot_size": int(lot) if lot is not None else None,
            "offer_price": _num(cells[5]),        # may be a range 'a-b' -> None
            "listing_price": _num(cells[6]),
            "oversub_rate": _num(cells[7]),
            "applied_lots_for_1": cells[8] if cells[8] not in ("N/A", "") else None,
            "one_lot_success_pct": _num(cells[9]),
        })
    return out


def upsert_bronze(cur, rows):
    n = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO bronze.aastocks_ipo_listed_raw
              (symbol, stock_name, listing_date, lot_size, market_cap_range,
               offer_price, listing_price, oversub_rate, applied_lots_for_1,
               one_lot_success_pct, scraped_at)
            VALUES (%s,%s,%s,%s,NULL,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (symbol) DO UPDATE SET
              stock_name          = EXCLUDED.stock_name,
              listing_date        = EXCLUDED.listing_date,
              lot_size            = EXCLUDED.lot_size,
              offer_price         = EXCLUDED.offer_price,
              listing_price       = EXCLUDED.listing_price,
              oversub_rate        = EXCLUDED.oversub_rate,
              applied_lots_for_1  = EXCLUDED.applied_lots_for_1,
              one_lot_success_pct = EXCLUDED.one_lot_success_pct,
              scraped_at          = NOW();
            """,
            (r["symbol"], r["stock_name"], r["listing_date"], r["lot_size"],
             r["offer_price"], r["listing_price"], r["oversub_rate"],
             r["applied_lots_for_1"], r["one_lot_success_pct"]),
        )
        n += 1
    return n


def upsert_silver(cur, rows):
    inserted = updated = 0
    for r in rows:
        px = r["listing_price"] or r["offer_price"]
        cur.execute(
            """
            INSERT INTO silver.unified_ipo_calendar
              (ticker, stock_name, listing_date, offer_price, currency,
               lot_size, oversubscription_retail, one_lot_success_pct,
               applied_lots_for_1_lot, data_source, first_seen_at, updated_at)
            VALUES (%s,%s,%s,%s,'HKD',%s,%s,%s,NULL,'aastocks_daily',
                    NOW(), NOW())
            ON CONFLICT (ticker, listing_date) DO UPDATE SET
              stock_name = COALESCE(silver.unified_ipo_calendar.stock_name,
                                    EXCLUDED.stock_name),
              offer_price = COALESCE(silver.unified_ipo_calendar.offer_price,
                                     EXCLUDED.offer_price),
              lot_size = COALESCE(EXCLUDED.lot_size,
                                  silver.unified_ipo_calendar.lot_size),
              oversubscription_retail = COALESCE(
                  EXCLUDED.oversubscription_retail,
                  silver.unified_ipo_calendar.oversubscription_retail),
              one_lot_success_pct = COALESCE(
                  EXCLUDED.one_lot_success_pct,
                  silver.unified_ipo_calendar.one_lot_success_pct),
              data_source = CASE
                  WHEN silver.unified_ipo_calendar.data_source ILIKE '%%aastocks%%'
                  THEN silver.unified_ipo_calendar.data_source
                  ELSE COALESCE(silver.unified_ipo_calendar.data_source, '')
                       || '+aastocks'
              END,
              updated_at = NOW()
            RETURNING (xmax = 0) AS is_insert;
            """,
            (r["ticker"], r["stock_name"], r["listing_date"], px,
             r["lot_size"], r["oversub_rate"], r["one_lot_success_pct"]),
        )
        is_insert = cur.fetchone()[0]
        if is_insert:
            inserted += 1
        else:
            updated += 1
    return inserted, updated


def onboard_new_listings(cur, rows):
    """Newly LISTED tickers (listing_date <= today) -> gold.asset_registry so
    the bronze yfinance stage starts pulling prices next run."""
    listed = [r for r in rows if r["listing_date"] <= date.today()]
    if not listed:
        return 0
    tickers = [r["ticker"] for r in listed]
    cur.execute(
        "SELECT ticker FROM gold.asset_registry WHERE ticker = ANY(%s)",
        (tickers,))
    have = {row[0] for row in cur.fetchall()}
    n = 0
    for r in listed:
        if r["ticker"] in have:
            continue
        cur.execute(
            """
            INSERT INTO gold.asset_registry
              (ticker, name, asset_class, market, horizon, is_active,
               description, created_at, updated_at)
            VALUES (%s, %s, 'STOCK', 'HK', '1d', TRUE,
                    'auto-onboarded by refresh_ipo_calendar_daily (HK IPO '
                    'universe feed, kanban 5711f0bb); listed ' || %s,
                    NOW(), NOW())
            ON CONFLICT (ticker) DO NOTHING;
            """,
            (r["ticker"], r["stock_name"] or r["ticker"],
             str(r["listing_date"])),
        )
        n += cur.rowcount
    return n


def fill_zh_names(cur):
    """Fill stock_name_zh for silver rows still missing it, from the TC
    listed-IPO table (same pagination as the EN pass). Row-level match on
    (ticker, listing_date within 7d) to survive code reuse. Never overwrites
    an existing zh name. Added 2026-09-02 (t_437922f4)."""
    cur.execute("""SELECT ticker, listing_date FROM silver.unified_ipo_calendar
                   WHERE stock_name_zh IS NULL AND listing_date IS NOT NULL""")
    need = {}
    for ticker, ld in cur.fetchall():
        code5 = re.sub(r"\.HK$", "", ticker).zfill(5)
        need.setdefault(code5, []).append((ticker, ld))
    if not need:
        return 0
    filled = 0
    for page in range(1, N_PAGES + 1):
        try:
            resp = requests.get(TC_BASE_URL.format(page=page), headers=HEADERS,
                                timeout=30)
            resp.raise_for_status()
        except Exception as e:
            print(f"  zh page {page} ERROR: {e}")
            time.sleep(DELAY_S)
            continue
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table", class_="dataTable")
        if table is None:
            break
        parsed_any = False
        for tr in table.find_all("tr"):
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) < 13:
                continue
            m = CODE_RE.search(cells[1])
            if not m:
                continue
            parsed_any = True
            code5 = m.group(1)
            if code5 not in need:
                continue
            name = TC_NAME_JUNK_RE.sub("", cells[1][:m.start()]).strip()
            if not name or not CJK_RE.search(name):
                continue
            try:
                aa_date = datetime.strptime(cells[2], "%Y/%m/%d").date()
            except (ValueError, IndexError):
                aa_date = None
            best = None
            for ticker, ld in need[code5]:
                if aa_date is None or abs((ld - aa_date).days) <= 7:
                    best = (ticker, ld)
                    break
            if best is None:
                continue
            cur.execute("""UPDATE silver.unified_ipo_calendar
                           SET stock_name_zh = %s
                           WHERE ticker = %s AND listing_date = %s
                             AND stock_name_zh IS NULL""",
                        (name, best[0], best[1]))
            if cur.rowcount:
                filled += cur.rowcount
                need[code5] = [x for x in need[code5] if x != best]
        if not parsed_any:
            break
        if not any(need.values()):
            break
        time.sleep(DELAY_S)
    return filled


def _mark_freshness(error=None):
    try:
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='aastocks_ipo',
                                  asset_class='ipo', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


def main():
    global _row_errors
    all_rows = {}
    for page in range(1, N_PAGES + 1):
        try:
            resp = requests.get(BASE_URL.format(page=page), headers=HEADERS,
                                timeout=30)
            resp.raise_for_status()
            rows = parse_page(resp.text)
            if not rows:
                print(f"  page {page}: 0 rows parsed — stopping pagination "
                      f"(table layout change or end of list)")
                break
            for r in rows:
                all_rows[r["symbol"]] = r
            print(f"  page {page}: {len(rows)} rows")
        except Exception as e:
            _row_errors += 1
            print(f"  page {page} ERROR: {e}")
        time.sleep(DELAY_S)

    rows = list(all_rows.values())
    if not rows:
        _mark_freshness(error="0 rows scraped")
        print("FATAL: no rows scraped from AAStocks listed-IPO table")
        sys.exit(1)

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        n_bronze = upsert_bronze(cur, rows)
        n_ins, n_upd = upsert_silver(cur, rows)
        n_zh = fill_zh_names(cur)
        n_reg = onboard_new_listings(cur, rows)
        conn.commit()
    except Exception:
        conn.rollback()
        _mark_freshness(error="db write failed")
        raise
    finally:
        conn.close()

    # post-run quality metrics
    with_oversub = sum(1 for r in rows if r["oversub_rate"] is not None)
    upcoming = sum(1 for r in rows if r["listing_date"] > date.today())
    print(f"✅ IPO calendar daily refresh: scraped={len(rows)} "
          f"(with_oversub={with_oversub}, upcoming={upcoming}), "
          f"bronze_upserted={n_bronze}, silver inserted={n_ins} "
          f"updated={n_upd}, zh_names_filled={n_zh}, "
          f"asset_registry onboarded={n_reg}")

    if _row_errors > 5:
        _mark_freshness(error=f"page_errors={_row_errors}")
        print(f"  ⚠️ {_row_errors} page errors exceeds threshold (5)")
        sys.exit(1)
    _mark_freshness()


if __name__ == "__main__":
    main()
