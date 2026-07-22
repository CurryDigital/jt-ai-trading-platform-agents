#!/usr/bin/env python3
"""One-off yfinance backfill for universe tickers to close gaps in 300-day window."""
import sys, os
from datetime import datetime, date, timedelta
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
import yfinance as yf
from db import get_connection
from psycopg2.extras import execute_values

START = date(2025, 1, 1)
END = date(2026, 7, 19)

UNIVERSE = [
    'AAPL','MSFT','AMZN','GOOGL','META','TSLA','NVDA','JPM','JNJ','V','UNH','XOM','WMT','PG','MA','HD','CVX','LLY','ABBV','MRK','BAC','PEP','KO','COST','TMO','DIS','MCD','CSCO','PFE','ACN','VZ','ADBE','CMCSA','NKE','TXN','HON','AMGN','IBM','LOW','UNP','QCOM','SPGI','PM','INTU','RTX','MDT','GS','CVS','DE','BLK','TGT','SBUX','CAT','AXP','AMAT','ISRG','GILD','MS','SCHW','LMT','PYPL','ADP','MDLZ','CSX','EL','GE','TJX','ITW','C','ZTS','NOC','USB','DUK','SO','CI','BDX','MMM','PLD','CCI','KMB','O','CL','NSC','EW','APD','FISV','PNC','FIS','SHW','CME','PSA','EQIX','ICE','MCO','COF','MET','TRV','DHR','AON','SLB','APTV','SPY','QQQ','IWM','TLT','IEF','AGG','HYG','JNK','LQD','EMB','GLD','SLV','GDX','SOXX',
]

UPSERT_TEMPLATE = "(%s, %s, %s, %s, %s, %s, %s, %s, NOW())"


def fetch_batch(tickers, start, end):
    """Fetch all tickers in a single yfinance call."""
    data = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        progress=False,
        threads=True,
    )
    rows = []
    if len(tickers) == 1:
        t = tickers[0]
        if data.empty:
            return rows
        for idx, row in data.iterrows():
            d = idx.date() if hasattr(idx, 'date') else idx
            rows.append((t, d,
                float(row['Open']) if 'Open' in row and row['Open'] is not None and str(row['Open']) != 'nan' else None,
                float(row['High']) if 'High' in row and row['High'] is not None and str(row['High']) != 'nan' else None,
                float(row['Low']) if 'Low' in row and row['Low'] is not None and str(row['Low']) != 'nan' else None,
                float(row['Close']) if 'Close' in row and row['Close'] is not None and str(row['Close']) != 'nan' else None,
                float(row['Adj Close']) if 'Adj Close' in row and row['Adj Close'] is not None and str(row['Adj Close']) != 'nan' else None,
                int(row['Volume']) if 'Volume' in row and row['Volume'] is not None and str(row['Volume']) != 'nan' else None,
            ))
    else:
        if data.empty:
            return rows
        for t in tickers:
            if t not in data['Close'].columns:
                continue
            for idx in data.index:
                d = idx.date() if hasattr(idx, 'date') else idx
                close = data[('Close', t)][idx]
                if close is None or str(close) == 'nan':
                    continue
                rows.append((t, d,
                    float(data[('Open', t)][idx]) if ('Open', t) in data and data[('Open', t)][idx] is not None and str(data[('Open', t)][idx]) != 'nan' else None,
                    float(data[('High', t)][idx]) if ('High', t) in data and data[('High', t)][idx] is not None and str(data[('High', t)][idx]) != 'nan' else None,
                    float(data[('Low', t)][idx]) if ('Low', t) in data and data[('Low', t)][idx] is not None and str(data[('Low', t)][idx]) != 'nan' else None,
                    float(close),
                    float(data[('Adj Close', t)][idx]) if ('Adj Close', t) in data and data[('Adj Close', t)][idx] is not None and str(data[('Adj Close', t)][idx]) != 'nan' else float(close),
                    int(data[('Volume', t)][idx]) if ('Volume', t) in data and data[('Volume', t)][idx] is not None and str(data[('Volume', t)][idx]) != 'nan' else None,
                ))
    return rows


def main():
    conn = get_connection()
    cur = conn.cursor()

    batch_size = 10
    total = 0
    for i in range(0, len(UNIVERSE), batch_size):
        batch = UNIVERSE[i:i+batch_size]
        print(f"Fetching batch {i+1}-{min(i+batch_size, len(UNIVERSE))}: {batch[:3]}...")
        rows = fetch_batch(batch, START, END)
        if rows:
            execute_values(cur, """
                INSERT INTO bronze.yf_prices (ticker, date, open, high, low, close, volume, adjusted_close, ingested_at)
                VALUES %s
                ON CONFLICT (ticker, date) DO UPDATE SET
                    open = COALESCE(EXCLUDED.open, bronze.yf_prices.open),
                    high = COALESCE(EXCLUDED.high, bronze.yf_prices.high),
                    low = COALESCE(EXCLUDED.low, bronze.yf_prices.low),
                    close = COALESCE(EXCLUDED.close, bronze.yf_prices.close),
                    volume = COALESCE(EXCLUDED.volume, bronze.yf_prices.volume),
                    adjusted_close = COALESCE(EXCLUDED.adjusted_close, bronze.yf_prices.adjusted_close);
            """, rows, template=UPSERT_TEMPLATE, page_size=1000)
            conn.commit()
            total += len(rows)
            print(f"  upserted {len(rows)} rows")
        else:
            print(f"  no rows returned")

    print(f"✅ bronze.yf_prices backfill: {total} rows upserted")
    conn.close()


if __name__ == '__main__':
    main()
