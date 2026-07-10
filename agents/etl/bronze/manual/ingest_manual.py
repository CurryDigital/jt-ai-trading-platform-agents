#!/usr/bin/env python3
"""
Bronze Ingestion: Manual Data Entry
Tables:
  bronze.manual_prices
  bronze.manual_earnings
Source: Manually entered CSV or direct DB inserts
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

def ingest_manual_prices(csv_path: str = None):
    """Load manually entered price data from CSV."""
    conn = get_connection()
    cur = conn.cursor()
    if csv_path:
        import csv
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute("""
                    INSERT INTO bronze.manual_prices
                        (ticker, date, open, high, low, close, volume, source_notes, entered_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, date) DO NOTHING
                """, (
                    row['ticker'], row['date'],
                    row.get('open'), row.get('high'), row.get('low'),
                    row.get('close'), row.get('volume'),
                    row.get('source_notes'), row.get('entered_by', 'manual')
                ))
    conn.commit()
    conn.close()
    print("✅ bronze.manual_prices ingested")

def ingest_manual_earnings(csv_path: str = None):
    """Load manually entered earnings data from CSV."""
    conn = get_connection()
    cur = conn.cursor()
    if csv_path:
        import csv
        with open(csv_path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                cur.execute("""
                    INSERT INTO bronze.manual_earnings
                        (ticker, report_date, fiscal_quarter, eps_estimate, eps_actual,
                         revenue_estimate, revenue_actual, source_notes, entered_by)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (ticker, report_date) DO NOTHING
                """, (
                    row['ticker'], row['report_date'], row.get('fiscal_quarter'),
                    row.get('eps_estimate'), row.get('eps_actual'),
                    row.get('revenue_estimate'), row.get('revenue_actual'),
                    row.get('source_notes'), row.get('entered_by', 'manual')
                ))
    conn.commit()
    conn.close()
    print("✅ bronze.manual_earnings ingested")



def _mark_freshness(error=None):
    """Update gold.source_freshness for the operator dashboard. Soft-fails."""
    try:
        from db import get_connection
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='manual', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")

if __name__ == "__main__":
    # 2026-07-10: absorbed load_manual.py — a second CLI writing the same two
    # tables with near-identical INSERTs. Cron mode (no args) is a no-op write
    # that just marks freshness; operator mode passes --prices/--earnings.
    import argparse
    parser = argparse.ArgumentParser(description="Manual data entry ingest")
    parser.add_argument('--prices',   help='Path to prices CSV')
    parser.add_argument('--earnings', help='Path to earnings CSV')
    args = parser.parse_args()
    try:
        ingest_manual_prices(args.prices)
        ingest_manual_earnings(args.earnings)
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
