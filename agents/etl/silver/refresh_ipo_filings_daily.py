#!/usr/bin/env python3
"""
Silver: daily HK IPO *pre-subscription filings* refresh — HKEXnews A1/PHIP
(kanban t_59228b1e, 2026-09-05)
================================================================
Purpose: feed the Strategies > IPO 'ANNOUNCED' stage. The calendar feeds
(NLR via refresh_ipo_calendar_daily.py, AAStocks via
refresh_ipo_upcoming_daily.py) only gain rows once application/listing
dates exist, so companies that have FILED (A1 application proof) or PASSED
HEARING (PHIP) but not yet opened subscription were invisible.

Source: HKEXnews 'Application Proofs, PHIPs and related materials' appindex
JSON feeds (verified 2026-09-05):
  https://www1.hkexnews.hk/ncms/json/eds/appactive_app_sehk_e.json
      active A1 applications (no PHIP yet), English names
  https://www1.hkexnews.hk/ncms/json/eds/appactive_appphip_sehk_e.json
      active applications WITH PHIP posted (passed hearing)
  *_gem_*  - GEM board variants
  *_c.json - Chinese-name variants (joined on applicant 'id')
  applisted_sehk_e.json / applisted_gem_e.json
      listed applicants incl. 'st' stock code -> deterministic
      reconciliation id -> ticker (no fuzzy name matching)

Entry fields: id (HKEX applicant id), d (latest doc date DD/MM/YYYY),
a (applicant name), ls[] doc list ('Application Proof (.. submission)'),
ps[] PHIP doc list, hasPhip, sA/sD (unused counters).

Flow per run:
  1. bronze.hkex_ipo_appindex_raw - append raw JSON snapshots (audit)
  2. silver.hk_ipo_filings        - upsert current active applicants
       (board, applicant_id): names, filing_stage, first_filing_date,
       latest_event_date, phip_date; reconcile status:
         in active feed          -> 'active'
         not active, in applisted-> 'listed' + listed_stock_code
         not active, not listed  -> 'lapsed'
  3. gold.source_freshness        - mark_source_refreshed('hkex_ipo_filings')

Does NOT write gold.hk_ipo_calendar (gold/ipo/build_ipo_announced.py
promotes active filings to placeholder rows in the gold stage).

Idempotent. Network/JSON errors hard-fail (no partial silver state).
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..', 'shared', 'scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection  # noqa: E402

try:
    import requests
except ImportError as e:
    print(f"missing package: {e.name} — etl-venv needs requests")
    sys.exit(1)

BASE = "https://www1.hkexnews.hk/ncms/json/eds/"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}
TIMEOUT_S = 30

# (file_name, board, stage) — 'app' = A1 only, 'appphip' = passed hearing
ACTIVE_FEEDS = [
    ("appactive_app_sehk_e.json",     "MAIN", "A1"),
    ("appactive_appphip_sehk_e.json", "MAIN", "PHIP"),
    ("appactive_app_gem_e.json",      "GEM",  "A1"),
    ("appactive_appphip_gem_e.json",  "GEM",  "PHIP"),
]
# Chinese-name mirrors, joined on applicant id
ZH_FEEDS = {
    "MAIN": ["appactive_app_sehk_c.json", "appactive_appphip_sehk_c.json"],
    "GEM":  ["appactive_app_gem_c.json", "appactive_appphip_gem_c.json"],
}
LISTED_FEEDS = {
    "MAIN": "applisted_sehk_e.json",
    "GEM":  "applisted_gem_e.json",
}


def fetch_json(file_name):
    r = requests.get(BASE + file_name, headers=HEADERS, timeout=TIMEOUT_S)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or "app" not in data:
        raise ValueError(f"{file_name}: unexpected payload shape")
    return data


def parse_dmy(s):
    """'17/10/2025' -> date; None on failure."""
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d/%m/%Y").date()
    except ValueError:
        return None


def doc_dates(entry, needle):
    """Dates of doc entries whose nF starts with `needle` (EN feeds)."""
    out = []
    for doc in (entry.get("ls") or []) + (entry.get("ps") or []):
        nf = doc.get("nF") or ""
        if nf.startswith(needle):
            d = parse_dmy(doc.get("d"))
            if d:
                out.append(d)
    return out


def fill_calendar_board(cur):
    """Backfill silver.unified_ipo_calendar.board (kanban t_33748a1d).

    Root cause fixed here: the AAStocks calendar ingest never writes board,
    so every listing first seen after the 2026-08-30 NLR backfill era got
    board=NULL, silently excluding Main-board events from the C1 engine
    (board='Main' filter) and forcing the paper feeder onto a ticker-prefix
    fallback -> feeder/engine event-set divergence.

    Fill hierarchy:
      1. silver.hk_ipo_filings.listed_stock_code (HKEXnews applisted feed
         reconciliation, authoritative; filings board 'MAIN' maps to the
         calendar's 'Main' casing, 'GEM' stays 'GEM').
      2. HKEX code-range convention (08001-08999 = GEM, else Main) for rows
         the applisted feed has not caught up with yet (feed lags up to ~2
         weeks around listing). Verified 2026-10-26: 0/1550 labeled rows
         conflict with the code-range rule. Provenance-tagged so audits can
         distinguish derived rows.

    Fill-NULL only; never overwrites an existing board value.
    Returns (n_from_filings, n_from_code_range).
    """
    cur.execute(
        """
        UPDATE silver.unified_ipo_calendar c
        SET board = CASE WHEN f.board = 'MAIN' THEN 'Main' ELSE f.board END,
            data_source = COALESCE(c.data_source, '') || '+hkex_filings_board',
            updated_at = NOW()
        FROM silver.hk_ipo_filings f
        WHERE c.board IS NULL
          AND f.status = 'listed'
          AND f.listed_stock_code = lpad(split_part(c.ticker, '.', 1), 5, '0')
        """)
    n_filings = cur.rowcount
    cur.execute(
        """
        UPDATE silver.unified_ipo_calendar
        SET board = CASE WHEN split_part(ticker, '.', 1) LIKE '8%'
                         THEN 'GEM' ELSE 'Main' END,
            data_source = COALESCE(data_source, '') || '+hkex_code_range_board',
            updated_at = NOW()
        WHERE board IS NULL
          AND ticker ~ '^[0-9]{4,5}\\.HK$'
        """)
    n_range = cur.rowcount
    return n_filings, n_range


def board_qa_gate(cur):
    """QA gate (kanban t_33748a1d): NULL board on a listed IPO
    (listing_date <= today) is an INGEST FAILURE, not a silent pass.
    Returns list of offending (ticker, listing_date); empty = pass."""
    cur.execute(
        """
        SELECT ticker, listing_date FROM silver.unified_ipo_calendar
        WHERE board IS NULL AND listing_date <= CURRENT_DATE
        ORDER BY listing_date
        """)
    return cur.fetchall()


def main():
    conn = get_connection()
    cur = conn.cursor()
    fetched_at = datetime.now(timezone.utc)

    # 1. Fetch everything up front; any failure aborts before touching silver.
    payloads = {}
    for file_name, _, _ in ACTIVE_FEEDS:
        payloads[file_name] = fetch_json(file_name)
    zh_payloads = {}
    for board, names in ZH_FEEDS.items():
        for n in names:
            zh_payloads[n] = fetch_json(n)
    listed_payloads = {}
    for board, n in LISTED_FEEDS.items():
        listed_payloads[board] = fetch_json(n)

    # 2. Bronze raw snapshots (append-only audit).
    for file_name, data in {**payloads, **zh_payloads,
                            **{n: listed_payloads[b] for b, n in LISTED_FEEDS.items()}}.items():
        cur.execute(
            "INSERT INTO bronze.hkex_ipo_appindex_raw (file_name, fetched_at, payload)"
            " VALUES (%s, %s, %s::jsonb)",
            (file_name, fetched_at, json.dumps(data)),
        )

    # 3. zh name map: (board, id) -> zh name
    zh_map = {}
    for board, names in ZH_FEEDS.items():
        for n in names:
            for e in zh_payloads[n]["app"]:
                zh_map[(board, e["id"])] = e.get("a")

    # 4. listed map: (board, id) -> stock code 'st' (5-digit zero-padded)
    listed_map = {}
    for board, data in listed_payloads.items():
        for e in data["app"]:
            st = e.get("st")
            if st:
                listed_map[(board, e["id"])] = st

    # 5. Upsert active applicants.
    active_keys = set()
    upserted = 0
    feed_udates = set()
    for file_name, board, stage in ACTIVE_FEEDS:
        data = payloads[file_name]
        udate = parse_dmy(data.get("uDate"))
        if udate:
            feed_udates.add(udate)
        for e in data["app"]:
            app_id = e["id"]
            key = (board, app_id)
            if key in active_keys:
                print(f"⚠️  duplicate active entry {board} {app_id} across feeds; first wins")
                continue
            active_keys.add(key)
            ap_dates = doc_dates(e, "Application Proof")
            phip_dates = doc_dates(e, "PHIP")
            first_filing = min(ap_dates) if ap_dates else parse_dmy(e.get("d"))
            phip_date = max(phip_dates) if phip_dates else None
            cur.execute(
                """
                INSERT INTO silver.hk_ipo_filings
                    (applicant_id, board, company_name_en, company_name_zh,
                     filing_stage, first_filing_date, latest_event_date,
                     phip_date, status, source_udate, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, NOW())
                ON CONFLICT (board, applicant_id) DO UPDATE SET
                    company_name_en   = EXCLUDED.company_name_en,
                    company_name_zh   = COALESCE(EXCLUDED.company_name_zh,
                                                 silver.hk_ipo_filings.company_name_zh),
                    filing_stage      = EXCLUDED.filing_stage,
                    first_filing_date = COALESCE(silver.hk_ipo_filings.first_filing_date,
                                                 EXCLUDED.first_filing_date),
                    latest_event_date = EXCLUDED.latest_event_date,
                    phip_date         = COALESCE(EXCLUDED.phip_date,
                                                 silver.hk_ipo_filings.phip_date),
                    status            = 'active',
                    source_udate      = EXCLUDED.source_udate,
                    updated_at        = NOW()
                """,
                (app_id, board, e.get("a") or "", zh_map.get(key),
                 stage, first_filing, parse_dmy(e.get("d")),
                 phip_date, udate),
            )
            upserted += 1

    # 6. Reconcile rows that left the active feed.
    cur.execute("SELECT board, applicant_id FROM silver.hk_ipo_filings WHERE status = 'active'")
    prev_active = {(r[0], r[1]) for r in cur.fetchall()}
    gone = prev_active - active_keys
    n_listed = n_lapsed = 0
    for board, app_id in gone:
        st = listed_map.get((board, app_id))
        if st:
            cur.execute(
                "UPDATE silver.hk_ipo_filings SET status='listed',"
                " listed_stock_code=%s, updated_at=NOW()"
                " WHERE board=%s AND applicant_id=%s",
                (st, board, app_id))
            n_listed += 1
        else:
            cur.execute(
                "UPDATE silver.hk_ipo_filings SET status='lapsed', updated_at=NOW()"
                " WHERE board=%s AND applicant_id=%s",
                (board, app_id))
            n_lapsed += 1

    # 6b. Board backfill onto the calendar + QA gate (t_33748a1d): a listed
    #     IPO with NULL board is an ingest failure, not a silent pass.
    n_bf_filings, n_bf_range = fill_calendar_board(cur)
    gate_failures = board_qa_gate(cur)

    # 7. Freshness stamp.
    from freshness import mark_source_refreshed
    mark_source_refreshed(
        conn, source='hkex_ipo_filings',
        max_date=max(feed_udates) if feed_udates else None,
        asset_class='HK_IPO')

    conn.commit()
    print(f"✅ silver.hk_ipo_filings: {upserted} active upserted across "
          f"{len(ACTIVE_FEEDS)} feeds, "
          f"{n_listed} newly listed, {n_lapsed} newly lapsed")
    print(f"   calendar board backfilled: {n_bf_filings} from filings, "
          f"{n_bf_range} from code range")
    per_feed = {f: len(p['app']) for f, p in payloads.items()}
    print(f"   feed sizes: {per_feed}")
    if gate_failures:
        tickers = ', '.join(f"{t}({d})" for t, d in gate_failures)
        print(f"FATAL: board QA gate — {len(gate_failures)} listed IPO(s) "
              f"with NULL board: {tickers}")
        sys.exit(1)
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
