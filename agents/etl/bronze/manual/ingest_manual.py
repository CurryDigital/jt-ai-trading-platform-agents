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

if __name__ == "__main__":
    ingest_manual_prices()
    ingest_manual_earnings()
