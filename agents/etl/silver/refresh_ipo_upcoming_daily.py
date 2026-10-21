#!/usr/bin/env python3
"""
Silver: daily HK IPO *upcoming* (subscription-window) refresh
(kanban t_e71cffde, 2026-09-02)
================================================================
Purpose: feed the Strategies > IPO 'IPO Under Subscription' panel —
forward-looking calendar rows with application open/close dates, offer
range and lot size. Complements refresh_ipo_calendar_daily.py (listed
IPOs, oversub stats), which carries no application-window fields.

Source: AAStocks upcoming-IPO pages (verified 2026-09-02)
  list:   /en/stocks/market/ipo/upcomingipo.aspx
          table.dataTable with 'Grey Market Date' header -> per-IPO rows
          (name/code, industry, offer price text, lot size, entry fee,
          closing date, grey market date, listing date)
  detail: /en/stocks/market/ipo/upcomingipo/company-summary?symbol=NNNNN
          'IPO Timetable' block -> Offer Period (application_start/end),
          Price-set / Allotment / Listing dates; 'IPO Info' block ->
          Lot Size, Offer Price, Sponsor(s)
Source 2 (2026-09-02, t_90585bf2): etnet IPO centre
  https://www.etnet.com.hk/www/eng/stocks/ci_ipo.php
          'Latest IPO' results table (Subscription Rate) -> fills on
          result-announcement day, 1-2 days BEFORE listing; lands
          oversubscription_retail pre-listing. NOTE: no free source
          publishes official multiples DURING the open window — NULL
          mid-window is truthful; multiples exist only post-window-close.

Flow per run:
  1. bronze.aastocks_ipo_upcoming_raw  - upsert raw rows (PK symbol)
  2. silver.unified_ipo_calendar       - upsert on (ticker, listing_date):
       * new upcoming IPOs inserted with application_start/end,
         allotment_date, lot_size, offer range (low/high or fixed_price)
       * existing rows get window fields filled/refreshed when the feed
         has values; never overwritten with NULL
  3. gold.source_freshness             - mark_source_refreshed('aastocks_ipo_upcoming')

Does NOT onboard tickers to gold.asset_registry (no prices before listing;
the listed-IPO daily script onboards at listing_date) and does NOT write
gold.hk_ipo_* (gold/ipo/build_ipo_data.py propagates silver -> gold).

Idempotent. Row errors tolerated up to 5, then non-zero exit.
"""
import os
import re
import sys
import time
from datetime import date, datetime, timedelta, timezone

HK_TZ = timezone(timedelta(hours=8))

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

LIST_URL = ("http://www.aastocks.com/en/stocks/market/ipo/upcomingipo.aspx")
DETAIL_URL = ("http://www.aastocks.com/en/stocks/market/ipo/upcomingipo/"
              "company-summary?symbol={symbol}&s=3&o=1&s3=1&o3=1")
# 2026-09-02 (t_90585bf2): etnet IPO centre carries a 'Latest IPO' results
# table (Subscription Rate / one-lot stats) that fills on RESULT ANNOUNCEMENT
# day — 1-2 days before listing, i.e. after the subscription window closes.
# This lands oversubscription_retail pre-listing instead of waiting for the
# post-listing AAStocks listed-IPO scrape.
ETNET_IPO_URL = "https://www.etnet.com.hk/www/eng/stocks/ci_ipo.php"
# 2026-09-30 (t_edb31797): per-code detail page carries a 'Subscription
# Result' box (Subscription Rate / One Lot Success Rate) that survives after
# the stock drops off BOTH the AAStocks upcoming list and etnet's own
# Latest-IPO list table (verified: 06802 detail still showed 3,546.91x on
# listing day while the ci_ipo.php list table read 'No related information.').
ETNET_DETAIL_URL = ("https://www.etnet.com.hk/www/eng/stocks/"
                    "ci_ipo_detail.php?code={code5}")
DELAY_S = 1.5
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
CODE_RE = re.compile(r"(\d{5})\.HK")
PERIOD_RE = re.compile(r"(\d{4}/\d{2}/\d{2})\s*-\s*(\d{4}/\d{2}/\d{2})")
DATE_RE = re.compile(r"(\d{4}/\d{2}/\d{2})")
RANGE_RE = re.compile(r"^([\d.]+)\s*-\s*([\d.]+)$")
# 2026-09-02 (t_90585bf2): A+H listings show "Max 240.6" (cap-only range).
MAXPX_RE = re.compile(r"^[Mm]ax\s+([\d.]+)$")
SUBRATE_RE = re.compile(r"^([\d,]+(?:\.\d+)?)x$", re.I)

# Coarse GICS-style sector for common AAStocks industry strings (silver
# convention from t_2f98c3be: sector = broad GICS sector, sub_sector =
# industry). Unmapped industries get sub_sector only; the post-listing
# yfinance backfill (fills sector IS NULL only) refines sector later.
INDUSTRY_SECTOR = {
    "health care equipment": "Health Care",
    "pharmaceuticals": "Health Care",
    "biotechnology": "Health Care",
    "semiconductors & semiconductor equipment": "Technology",
    "advanced hardware and software": "Technology",
    "software": "Technology",
    "internet software & services": "Technology",
    "apparel, accessories & luxury goods retail": "Consumer Cyclical",
    "food & beverage": "Consumer Defensive",
    "banks": "Financials",
    "insurance": "Financials",
    "real estate": "Real Estate",
    "industrials": "Industrials",
    "automobiles & components": "Consumer Cyclical",
    "energy": "Energy",
    "materials": "Basic Materials",
    "utilities": "Utilities",
    "telecommunication services": "Communication Services",
    "media & entertainment": "Communication Services",
}

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


def _date(s):
    if not s:
        return None
    m = DATE_RE.search(s)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y/%m/%d").date()
    except ValueError:
        return None


def parse_list(html):
    """Upcoming-IPO list rows from upcomingipo.aspx."""
    soup = BeautifulSoup(html, "html.parser")
    table = None
    for t in soup.find_all("table", class_="dataTable"):
        head = t.get_text(strip=True)
        if "Grey Market Date" in head and "Listing Date" in head:
            table = t
            break
    if table is None:
        return []
    out = []
    for tr in table.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all("td")]
        if len(cells) < 9:
            continue
        m = CODE_RE.search(cells[1])
        if not m:
            continue
        symbol = m.group(1)
        name = cells[1][:m.start()].strip() or None
        # AAStocks symbol is 5-digit zero-padded; DB convention is 4-digit.
        ticker4 = symbol[1:] if symbol.startswith("0") else symbol
        out.append({
            "symbol": symbol,
            "ticker": ticker4 + ".HK",
            "stock_name": name,
            "industry": cells[2] or None,
            "offer_price_text": cells[3] or None,
            "lot_size": int(_num(cells[4])) if _num(cells[4]) is not None else None,
            "entry_fee": _num(cells[5]),
            "closing_date": _date(cells[6]),
            "grey_market_date": _date(cells[7]),
            "listing_date": _date(cells[8]),
        })
    return out


def parse_detail(html):
    """Timetable + IPO-info fields from a company-summary page."""
    soup = BeautifulSoup(html, "html.parser")
    info = {"application_start": None, "application_end": None,
            "price_set_date": None, "allotment_date": None,
            "listing_date": None, "lot_size": None,
            "offer_price_text": None, "sponsor": None}
    for tr in soup.find_all("tr"):
        cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
        if len(cells) < 2:
            continue
        label, value = cells[0], cells[1]
        if label == "Offer Period":
            m = PERIOD_RE.search(value)
            if m:
                info["application_start"] = _date(m.group(1))
                info["application_end"] = _date(m.group(2))
        elif label == "Price-set Date":
            info["price_set_date"] = _date(value)
        elif label == "Allotment Date":
            info["allotment_date"] = _date(value)
        elif label == "Listing Date" and info["listing_date"] is None:
            info["listing_date"] = _date(value)
        elif label == "Lot Size":
            v = _num(value)
            info["lot_size"] = int(v) if v is not None else None
        elif label == "Offer Price":
            info["offer_price_text"] = value or None
        elif label == "Sponsor(s)":
            info["sponsor"] = value[:500] or None
    return info


def offer_fields(text):
    """'a-b' -> (low, high, None, False); 'x' -> (None, None, x, True);
    'Max x' (A+H cap-only) -> (None, x, None, False)."""
    if not text or text in ("N/A", "-"):
        return None, None, None, None
    m = RANGE_RE.match(text.strip())
    if m:
        return float(m.group(1)), float(m.group(2)), None, False
    m = MAXPX_RE.match(text.strip())
    if m:
        return None, float(m.group(1)), None, False
    v = _num(text)
    if v is not None:
        return None, None, v, True
    return None, None, None, None


def parse_etnet_results(html):
    """Oversubscription multiples from etnet IPO centre.

    Two tables carry 'Subscription Rate'; we use ONLY the pre-listing one:
      * 'Latest IPO' results table (no 'Open on Listing Date' column) — fills
        on result-announcement day, 1-2 days BEFORE listing. This is the
        pre-listing gap this feed exists to close.
      * 'Hot Listed IPO' (has 'Open on Listing Date') is SKIPPED: post-listing
        values belong to the AAStocks listed-IPO scrape (existing convention),
        and etnet rounds differently (3,835.36x vs AAStocks 3,834.4).
    Returns {ticker4: oversubscription_retail_float}.
    """
    soup = BeautifulSoup(html, "html.parser")
    out = {}
    for t in soup.find_all("table"):
        rows = t.find_all("tr")
        if not rows:
            continue
        hdr = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
        if "Subscription Rate" not in hdr or "Code" not in hdr:
            continue
        if "Open on Listing Date" in hdr:
            continue  # Hot Listed table — post-listing, not ours
        i_code = hdr.index("Code")
        i_rate = hdr.index("Subscription Rate")
        for tr in rows[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all(["th", "td"])]
            if len(cells) <= max(i_code, i_rate):
                continue
            m = re.match(r"^(\d{5})$", cells[i_code].replace("\xa0", "").strip())
            rate = SUBRATE_RE.match(cells[i_rate].strip())
            if not m or not rate:
                continue
            symbol = m.group(1)
            ticker4 = symbol[1:] if symbol.startswith("0") else symbol
            out[ticker4 + ".HK"] = float(rate.group(1).replace(",", ""))
    return out


ETNET_DETAIL_RATE_RE = re.compile(
    r"Subscription Rate</div>\s*<div>\s*([\d,]+(?:\.\d+)?)x\s*</div>", re.I)


def parse_etnet_detail_rate(html):
    """Subscription Rate from a per-code etnet detail page ('Subscription
    Result' box). Returns float or None when the box is absent / rate not
    yet published (pre-allotment pages have no box at all — not an error)."""
    m = ETNET_DETAIL_RATE_RE.search(html)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))


def fetch_allotment_cohort():
    """Allotment-date cohort from silver.unified_ipo_calendar (t_edb31797).

    AAStocks drops a ticker from its upcoming page on ALLOTMENT MORNING, and
    etnet's Latest-IPO list table can also be empty by the time the evening
    fill runs — so the etnet fetch must be driven by the silver calendar,
    not by any live scrape. Cohort = rows still missing
    oversubscription_retail whose allotment_date is near 'today' in HK time.

    Window is hk_today-2 .. hk_today (not just hk_today) because the evening
    fill fires at 16:30/18:30 UTC = 00:30/02:30 HKT the NEXT day — with a
    same-day window the 00:30 HKT run would miss tickers whose allotment
    day just ended (exactly the 6802.HK 2026-09-29 miss).
    """
    hk_today = datetime.now(HK_TZ).date()
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ticker FROM silver.unified_ipo_calendar
            WHERE oversubscription_retail IS NULL
              AND allotment_date BETWEEN %s AND %s
              AND ticker LIKE '%%.HK'
            ORDER BY allotment_date, ticker;
            """,
            (hk_today - timedelta(days=2), hk_today),
        )
        return [r[0] for r in cur.fetchall()]
    finally:
        conn.close()


def fetch_etnet_detail_rates(tickers):
    """Fetch per-code etnet detail pages for cohort tickers not already
    covered by the list-table parse. Returns {ticker: rate}; tickers whose
    results are not yet published are simply absent."""
    out = {}
    for ticker in tickers:
        code4 = ticker.split(".")[0]
        code5 = code4.zfill(5)
        try:
            r = requests.get(ETNET_DETAIL_URL.format(code5=code5),
                             headers=HEADERS, timeout=30)
            r.raise_for_status()
            rate = parse_etnet_detail_rate(r.text)
            if rate is not None:
                out[ticker] = rate
                print(f"  etnet detail {ticker}: subscription rate {rate}x")
            else:
                print(f"  etnet detail {ticker}: no subscription rate yet")
        except Exception as ex:
            print(f"  etnet detail {ticker} ERROR (non-fatal): {ex}")
        time.sleep(DELAY_S)
    return out


def upsert_bronze(cur, rows):
    n = 0
    for r in rows:
        cur.execute(
            """
            INSERT INTO bronze.aastocks_ipo_upcoming_raw
              (symbol, stock_name, industry, offer_price_text, lot_size,
               entry_fee, closing_date, grey_market_date, listing_date,
               application_start, application_end, price_set_date,
               allotment_date, sponsor, scraped_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            ON CONFLICT (symbol) DO UPDATE SET
              stock_name        = EXCLUDED.stock_name,
              industry          = EXCLUDED.industry,
              offer_price_text  = EXCLUDED.offer_price_text,
              lot_size          = EXCLUDED.lot_size,
              entry_fee         = EXCLUDED.entry_fee,
              closing_date      = EXCLUDED.closing_date,
              grey_market_date  = EXCLUDED.grey_market_date,
              listing_date      = EXCLUDED.listing_date,
              application_start = EXCLUDED.application_start,
              application_end   = EXCLUDED.application_end,
              price_set_date    = EXCLUDED.price_set_date,
              allotment_date    = EXCLUDED.allotment_date,
              sponsor           = EXCLUDED.sponsor,
              scraped_at        = NOW();
            """,
            (r["symbol"], r["stock_name"], r["industry"], r["offer_price_text"],
             r["lot_size"], r["entry_fee"], r["closing_date"],
             r["grey_market_date"], r["listing_date"], r["application_start"],
             r["application_end"], r["price_set_date"], r["allotment_date"],
             r["sponsor"]),
        )
        n += 1
    return n


def upsert_silver(cur, rows, etnet_rates):
    inserted = updated = 0
    for r in rows:
        if r["listing_date"] is None:
            print(f"  skip {r['symbol']}: no listing_date")
            continue
        low, high, fixed, is_fixed = offer_fields(r["offer_price_text"])
        # 2026-09-02 (t_90585bf2): AAStocks industry -> sub_sector; coarse
        # sector via INDUSTRY_SECTOR map (GICS-style convention, t_2f98c3be).
        sub_sector = (r.get("industry") or "")[:200] or None
        sector = INDUSTRY_SECTOR.get((r.get("industry") or "").strip().lower())
        oversub = etnet_rates.get(r["ticker"])
        cur.execute(
            """
            INSERT INTO silver.unified_ipo_calendar
              (ticker, stock_name, listing_date, offer_price, currency,
               offer_price_low, offer_price_high, fixed_price, lot_size,
               application_start, application_end, allotment_date,
               sector, sub_sector, oversubscription_retail,
               sponsor, data_source, first_seen_at, updated_at)
            VALUES (%s,%s,%s,%s,'HKD',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                    'aastocks_upcoming', NOW(), NOW())
            ON CONFLICT (ticker, listing_date) DO UPDATE SET
              stock_name = COALESCE(silver.unified_ipo_calendar.stock_name,
                                    EXCLUDED.stock_name),
              offer_price = COALESCE(silver.unified_ipo_calendar.offer_price,
                                     EXCLUDED.offer_price),
              offer_price_low = COALESCE(EXCLUDED.offer_price_low,
                                  silver.unified_ipo_calendar.offer_price_low),
              offer_price_high = COALESCE(EXCLUDED.offer_price_high,
                                  silver.unified_ipo_calendar.offer_price_high),
              fixed_price = COALESCE(EXCLUDED.fixed_price,
                              silver.unified_ipo_calendar.fixed_price),
              lot_size = COALESCE(EXCLUDED.lot_size,
                                  silver.unified_ipo_calendar.lot_size),
              application_start = COALESCE(EXCLUDED.application_start,
                                  silver.unified_ipo_calendar.application_start),
              application_end = COALESCE(EXCLUDED.application_end,
                                  silver.unified_ipo_calendar.application_end),
              allotment_date = COALESCE(EXCLUDED.allotment_date,
                                  silver.unified_ipo_calendar.allotment_date),
              -- fill NULL only; yfinance backfill refines sector post-listing
              sector = COALESCE(silver.unified_ipo_calendar.sector,
                                EXCLUDED.sector),
              sub_sector = COALESCE(silver.unified_ipo_calendar.sub_sector,
                                    EXCLUDED.sub_sector),
              -- etnet allotment-results fill (NULL only; the post-listing
              -- AAStocks listed-IPO scrape remains the final authority)
              oversubscription_retail = COALESCE(
                                  silver.unified_ipo_calendar.oversubscription_retail,
                                  EXCLUDED.oversubscription_retail),
              sponsor = COALESCE(silver.unified_ipo_calendar.sponsor,
                                 EXCLUDED.sponsor),
              data_source = CASE
                  WHEN silver.unified_ipo_calendar.data_source ILIKE '%%aastocks%%'
                  THEN silver.unified_ipo_calendar.data_source
                  ELSE COALESCE(silver.unified_ipo_calendar.data_source, '')
                       || '+aastocks_upcoming'
              END,
              updated_at = NOW()
            RETURNING (xmax = 0) AS is_insert;
            """,
            (r["ticker"], r["stock_name"], r["listing_date"], fixed,
             low, high, is_fixed, r["lot_size"], r["application_start"],
             r["application_end"], r["allotment_date"], sector, sub_sector,
             oversub, r["sponsor"]),
        )
        if cur.fetchone()[0]:
            inserted += 1
        else:
            updated += 1
    return inserted, updated

def apply_etnet_orphans(cur, etnet_rates, row_tickers):
    """Second pass (t_64a41639, 2026-09-29): AAStocks drops a ticker from the
    upcoming page on ALLOTMENT MORNING — hours before etnet publishes results
    that evening — so the rows-driven upsert above never sees allotment-day
    cohorts (verified: 06802 last in bronze scrape 2026-09-28 08:42 UTC,
    absent 2026-09-29; etnet Latest IPO still carries it pre-listing).
    Apply parsed etnet rates to EXISTING silver rows directly.

    Guards: NULL-only fill (the post-listing AAStocks listed-IPO scrape stays
    final authority and is never clobbered) and listing_date >= today (only
    pre-listing / listing-day rows are touched)."""
    n = 0
    for ticker, rate in etnet_rates.items():
        if ticker in row_tickers:
            continue  # already handled by the rows-driven upsert (COALESCE)
        cur.execute(
            """
            UPDATE silver.unified_ipo_calendar
            SET oversubscription_retail = %s, updated_at = NOW()
            WHERE ticker = %s
              AND oversubscription_retail IS NULL
              AND listing_date >= CURRENT_DATE;
            """,
            (rate, ticker),
        )
        if cur.rowcount:
            print(f"  etnet 2nd-pass: {ticker} oversubscription_retail={rate} "
                  f"({cur.rowcount} row)")
        n += cur.rowcount
    return n


def _mark_freshness(error=None):
    try:
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='aastocks_ipo_upcoming',
                                  asset_class='ipo', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


def main():
    global _row_errors
    resp = requests.get(LIST_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    rows = parse_list(resp.text)
    print(f"  list: {len(rows)} upcoming IPOs")
    if not rows:
        # An empty upcoming list is plausible (quiet IPO market) but also the
        # signature of a layout change; treat as error so freshness flags it.
        _mark_freshness(error="0 upcoming rows parsed (layout change?)")
        print("FATAL: no upcoming rows parsed from AAStocks")
        sys.exit(1)

    for r in rows:
        try:
            d = requests.get(DETAIL_URL.format(symbol=r["symbol"]),
                             headers=HEADERS, timeout=30)
            d.raise_for_status()
            info = parse_detail(d.text)
            r.update(info)
            # detail-page values win over list values when present
            if info["listing_date"]:
                r["listing_date"] = info["listing_date"]
            if info["lot_size"]:
                r["lot_size"] = info["lot_size"]
            if info["offer_price_text"] and info["offer_price_text"] != "N/A":
                r["offer_price_text"] = info["offer_price_text"]
            print(f"  {r['symbol']} {r['stock_name']}: window "
                  f"{r['application_start']}..{r['application_end']}, "
                  f"listing {r['listing_date']}, px {r['offer_price_text']}")
        except Exception as e:
            _row_errors += 1
            print(f"  {r['symbol']} detail ERROR: {e}")
        time.sleep(DELAY_S)

    # etnet allotment-results table: oversubscription multiples for IPOs
    # between result-announcement and listing (pre-listing fill).
    etnet_rates = {}
    try:
        e = requests.get(ETNET_IPO_URL, headers=HEADERS, timeout=30)
        e.raise_for_status()
        etnet_rates = parse_etnet_results(e.text)
        print(f"  etnet list-table results: {len(etnet_rates)} tickers "
              f"({sorted(etnet_rates)})")
    except Exception as ex:
        # Non-fatal: AAStocks listed-IPO scrape backfills post-listing anyway.
        print(f"  etnet results fetch failed (non-fatal): {ex}")

    # t_edb31797: allotment-day cohort from silver.unified_ipo_calendar —
    # independent of the live AAStocks upcoming scrape (AAStocks drops
    # tickers on allotment morning) AND of etnet's own list table (which
    # read 'No related information.' on 6802.HK's allotment evening).
    # Per-code detail pages keep the Subscription Result box regardless.
    try:
        cohort = fetch_allotment_cohort()
        if cohort:
            print(f"  allotment-date cohort (silver, HK window): {cohort}")
            missing = [t for t in cohort if t not in etnet_rates]
            detail_rates = fetch_etnet_detail_rates(missing)
            etnet_rates.update(detail_rates)
    except Exception as ex:
        print(f"  etnet cohort fetch failed (non-fatal): {ex}")
    print(f"  etnet allotment results: {len(etnet_rates)} tickers "
          f"({sorted(etnet_rates)})")

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        n_bronze = upsert_bronze(cur, rows)
        n_ins, n_upd = upsert_silver(cur, rows, etnet_rates)
        # t_64a41639: allotment-day cohorts are already off the AAStocks
        # upcoming page when etnet publishes — apply rates to existing rows.
        n_orphan = apply_etnet_orphans(cur, etnet_rates,
                                       {r["ticker"] for r in rows})
        conn.commit()
    except Exception:
        conn.rollback()
        _mark_freshness(error="db write failed")
        raise
    finally:
        conn.close()

    in_window = sum(1 for r in rows
                    if r["application_end"] and r["application_end"] >= date.today())
    print(f"✅ upcoming IPO refresh: scraped={len(rows)} "
          f"(in_window={in_window}), bronze_upserted={n_bronze}, "
          f"silver inserted={n_ins} updated={n_upd} "
          f"etnet_2nd_pass={n_orphan}")

    if _row_errors > 5:
        _mark_freshness(error=f"detail_errors={_row_errors}")
        print(f"  ⚠️ {_row_errors} detail errors exceeds threshold (5)")
        sys.exit(1)
    _mark_freshness()


if __name__ == "__main__":
    main()
