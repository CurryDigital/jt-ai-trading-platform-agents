#!/usr/bin/env python3
"""
Bronze Ingestion: HKEX
Tables:
  bronze.hkex_ipo_calendar_raw   — upcoming / recent IPO listings
  bronze.hkex_ipo_prices_raw     — daily price data for newly listed stocks
  bronze.hkex_ipo_prospectus_raw — key prospectus data (oversubscription, cornerstone)
Source: HKEX website + yfinance for price data after listing
"""
import sys, os, json
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta

try:
    import requests
    import yfinance as yf
except ImportError as e:
    print(f"⚠️  Missing dependency: {e} — run: pip install requests yfinance")
    sys.exit(1)

HKEX_IPO_URL = 'https://www.hkex.com.hk/eng/services/trading/securities/newlist/ipolist.aspx'

def get_pending_ipos(conn) -> list:
    """Get IPO tickers that have listing dates within the last 90 days."""
    cur = conn.cursor()
    cur.execute("""
        SELECT ticker, listing_date
        FROM bronze.hkex_ipo_calendar_raw
        WHERE listing_date >= CURRENT_DATE - INTERVAL '90 days'
          AND listing_date <= CURRENT_DATE
        ORDER BY listing_date DESC
    """)
    return cur.fetchall()


# ── IPO Calendar ──────────────────────────────────────────────────────────────

def ingest_ipo_calendar(manual_entries: list = None):
    """
    Upsert IPO calendar entries.
    manual_entries: list of dicts with keys:
        ticker, stock_name, listing_date, offer_price, market_cap_hkd,
        sector, sub_sector, sponsor, shares_offered
    """
    conn = get_connection()
    cur  = conn.cursor()
    inserted = 0

    entries = manual_entries or []
    for entry in entries:
        try:
            cur.execute("""
                INSERT INTO bronze.hkex_ipo_calendar_raw
                    (ticker, stock_name, listing_date, offer_price,
                     market_cap_hkd, sector, sub_sector, sponsor,
                     shares_offered, scraped_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (ticker, listing_date) DO UPDATE SET
                    offer_price    = EXCLUDED.offer_price,
                    market_cap_hkd = EXCLUDED.market_cap_hkd,
                    scraped_at     = NOW()
            """, (
                entry.get('ticker'),
                entry.get('stock_name'),
                entry.get('listing_date'),
                entry.get('offer_price'),
                entry.get('market_cap_hkd'),
                entry.get('sector'),
                entry.get('sub_sector'),
                entry.get('sponsor'),
                entry.get('shares_offered'),
            ))
            inserted += 1
        except Exception as e:
            print(f"    IPO entry error: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.hkex_ipo_calendar_raw — {inserted} rows upserted")


# ── IPO Prices (via yfinance) ────────────────────────────────────────────────

def ingest_ipo_prices(days_of_history: int = 90):
    """
    For each IPO in the calendar, fetch post-listing price data via yfinance.
    HKEX tickers in yfinance format: '0700.HK' for Tencent (ticker='0700')
    """
    conn = get_connection()
    cur  = conn.cursor()
    ipos = get_pending_ipos(conn)
    inserted = 0

    for ticker, listing_date in ipos:
        yf_ticker = f"{ticker}.HK" if not ticker.endswith('.HK') else ticker
        start     = listing_date.isoformat()
        end_dt    = listing_date + timedelta(days=days_of_history)

        try:
            data = yf.download(yf_ticker, start=start, end=end_dt.isoformat(),
                                auto_adjust=True, progress=False)
            if data.empty:
                continue
            days_since = 0
            for ts, row in data.iterrows():
                try:
                    cur.execute("""
                        INSERT INTO bronze.hkex_ipo_prices_raw
                            (ticker, price_date, open, high, low, close,
                             volume, adjusted_close, days_since_listing, fetched_at)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                        ON CONFLICT (ticker, price_date) DO UPDATE SET
                            close             = EXCLUDED.close,
                            days_since_listing = EXCLUDED.days_since_listing
                    """, (
                        ticker,
                        ts.date(),
                        float(row['Open'])   if row['Open']  == row['Open']  else None,
                        float(row['High'])   if row['High']  == row['High']  else None,
                        float(row['Low'])    if row['Low']   == row['Low']   else None,
                        float(row['Close'])  if row['Close'] == row['Close'] else None,
                        int(row['Volume'])   if row['Volume'] == row['Volume'] else None,
                        float(row['Close'])  if row['Close'] == row['Close'] else None,
                        days_since,
                    ))
                    inserted += 1
                    days_since += 1
                except Exception as e:
                    print(f"    Row error {ticker} {ts}: {e}")
        except Exception as e:
            print(f"  Price error {yf_ticker}: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.hkex_ipo_prices_raw — {inserted} rows upserted")


# ── IPO Prospectus Key Metrics ────────────────────────────────────────────────

def ingest_ipo_prospectus(manual_entries: list = None):
    """
    Upsert key prospectus data (oversubscription, cornerstone investors).
    manual_entries: list of dicts with keys:
        ticker, oversubscription_retail, oversubscription_institutional,
        cornerstone_total_pct, lockup_period_days, greenshoe_pct,
        use_of_proceeds
    """
    conn = get_connection()
    cur  = conn.cursor()
    inserted = 0

    for entry in (manual_entries or []):
        try:
            cur.execute("""
                INSERT INTO bronze.hkex_ipo_prospectus_raw
                    (ticker, oversubscription_retail, oversubscription_institutional,
                     cornerstone_total_pct, lockup_period_days,
                     greenshoe_pct, use_of_proceeds, scraped_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (ticker, announcement_id) DO UPDATE SET
                    oversubscription_retail        = EXCLUDED.oversubscription_retail,
                    oversubscription_institutional = EXCLUDED.oversubscription_institutional,
                    cornerstone_total_pct          = EXCLUDED.cornerstone_total_pct
            """, (
                entry.get('ticker'),
                entry.get('oversubscription_retail'),
                entry.get('oversubscription_institutional'),
                entry.get('cornerstone_total_pct'),
                entry.get('lockup_period_days'),
                entry.get('greenshoe_pct'),
                entry.get('use_of_proceeds'),
            ))
            inserted += 1
        except Exception as e:
            print(f"    Prospectus entry error: {e}")

    conn.commit()
    conn.close()
    print(f"✅ bronze.hkex_ipo_prospectus_raw — {inserted} rows upserted")




def _mark_freshness(error=None):
    """Update gold.source_freshness for the operator dashboard. Soft-fails."""
    try:
        from db import get_connection
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='hkex', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")

if __name__ == "__main__":
    try:
        ingest_ipo_calendar()
        ingest_ipo_prices()
        ingest_ipo_prospectus()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
