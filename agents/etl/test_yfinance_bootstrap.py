#!/usr/bin/env python3
"""Quick yfinance test for bootstrap."""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
import yfinance as yf
from datetime import date, timedelta

# Test with a single ticker
ticker = 'AAPL'
start = (date.today() - timedelta(days=5)).isoformat()
print(f"Testing yfinance fetch for {ticker} from {start}...")

data = yf.download(ticker, start=start, auto_adjust=True, progress=False)
print(f"Fetched {len(data)} rows")

# Try a bronze write
conn = get_connection()
cur = conn.cursor()
inserted = 0
for ts, row in data.iterrows():
    vals = row.values
    cur.execute("""
        INSERT INTO bronze.yf_prices
            (ticker, date, open, high, low, close, volume,
             adjusted_close, ingested_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (ticker, date) DO UPDATE SET
            close = EXCLUDED.close,
            volume = EXCLUDED.volume
    """, (
        ticker, ts.date(),
        float(vals[3]), float(vals[1]), float(vals[2]), float(vals[0]), int(vals[4]), float(vals[0]),
    ))
    inserted += 1
conn.commit()
conn.close()
print(f"✅ Test write complete — {inserted} rows to bronze.yf_prices")
