#!/usr/bin/env python3
"""
Bronze Ingestion: Manual Entry
Tables:
  bronze.manual_prices
  bronze.manual_earnings
Source: Human-entered data (CSV / direct insert)
"""
import sys, os, csv
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

def load_manual_prices(csv_path: str, entered_by: str = "manual"):
    """Load manually entered prices from CSV into bronze.manual_prices."""
    conn = get_connection()
    cur = conn.cursor()
    inserted = 0
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute("""
                INSERT INTO bronze.manual_prices
                  (ticker, date, open, high, low, close, volume, adjusted_close, entered_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, date) DO UPDATE SET
                  close = EXCLUDED.close,
                  entered_by = EXCLUDED.entered_by,
                  ingested_at = NOW()
            """, (
                row['ticker'], row['date'],
                row.get('open'), row.get('high'), row.get('low'), row.get('close'),
                row.get('volume'), row.get('adjusted_close'), entered_by
            ))
            inserted += 1
    conn.commit()
    conn.close()
    print(f"✅ bronze.manual_prices: {inserted} rows loaded")

def load_manual_earnings(csv_path: str, entered_by: str = "manual"):
    """Load manually entered earnings from CSV into bronze.manual_earnings."""
    conn = get_connection()
    cur = conn.cursor()
    inserted = 0
    with open(csv_path, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            cur.execute("""
                INSERT INTO bronze.manual_earnings
                  (ticker, report_date, fiscal_quarter, eps_estimate, eps_actual,
                   revenue_estimate, revenue_actual, entered_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (ticker, report_date) DO UPDATE SET
                  eps_actual = EXCLUDED.eps_actual,
                  entered_by = EXCLUDED.entered_by,
                  ingested_at = NOW()
            """, (
                row['ticker'], row['report_date'], row.get('fiscal_quarter'),
                row.get('eps_estimate'), row.get('eps_actual'),
                row.get('revenue_estimate'), row.get('revenue_actual'),
                entered_by
            ))
            inserted += 1
    conn.commit()
    conn.close()
    print(f"✅ bronze.manual_earnings: {inserted} rows loaded")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--prices',   help='Path to prices CSV')
    parser.add_argument('--earnings', help='Path to earnings CSV')
    parser.add_argument('--by',       default='manual', help='Entered by')
    args = parser.parse_args()
    if args.prices:
        load_manual_prices(args.prices, args.by)
    if args.earnings:
        load_manual_earnings(args.earnings, args.by)
