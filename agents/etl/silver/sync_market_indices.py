#!/usr/bin/env python3
"""
Silver: Market Indices Refresh
Reads from: silver.unified_prices (indices), silver.asset_registry
Writes to:  silver.market_indices
Ensures market indices are synced from unified_prices with proper metadata.
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

SQL = """
INSERT INTO silver.market_indices (
    ticker, date, name, market, region, currency,
    open, high, low, close, volume, change_pct, change_amount,
    ma_50, ma_200, above_ma_50, above_ma_200,
    ytd_change, is_volatility_index
)
WITH valid_indices AS (
    SELECT 
        up.ticker,
        up.date,
        up.open,
        up.high,
        up.low,
        up.close,
        up.volume,
        up.returns_1d * 100 as change_pct,
        up.close - LAG(up.close) OVER (PARTITION BY up.ticker ORDER BY up.date) as change_amount,
        CASE 
            WHEN up.ticker IN ('^GSPC', '^IXIC', '^DJI', '^RUT', '^VIX') THEN 'Americas'
            WHEN up.ticker IN ('^FTSE', '^FCHI', '^GDAXI', '^N100') THEN 'Europe'
            WHEN up.ticker IN ('^AXJO', '^HSI', '^N225', '000001.SS') THEN 'Asia'
            ELSE 'Unknown'
        END as region,
        CASE WHEN up.ticker IN ('^VIX', 'VIX') THEN TRUE ELSE FALSE END as is_volatility_index
    FROM silver.unified_prices up
    WHERE up.asset_class = 'INDEX'
      AND up.close IS NOT NULL
),
with_mas AS (
    SELECT 
        vi.ticker,
        vi.date,
        vi.open,
        vi.high,
        vi.low,
        vi.close,
        vi.volume,
        vi.change_pct,
        vi.change_amount,
        vi.region,
        vi.is_volatility_index,
        AVG(vi.close) OVER (PARTITION BY vi.ticker ORDER BY vi.date ROWS BETWEEN 49 PRECEDING AND CURRENT ROW) as ma_50,
        AVG(vi.close) OVER (PARTITION BY vi.ticker ORDER BY vi.date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) as ma_200
    FROM valid_indices vi
)
SELECT 
    with_mas.ticker,
    with_mas.date,
    ar.name,
    ar.market,
    with_mas.region,
    COALESCE(ar.currency, 'USD'),
    with_mas.open,
    with_mas.high,
    with_mas.low,
    with_mas.close,
    with_mas.volume,
    with_mas.change_pct,
    with_mas.change_amount,
    with_mas.ma_50,
    with_mas.ma_200,
    with_mas.close > with_mas.ma_50 as above_ma_50,
    with_mas.close > with_mas.ma_200 as above_ma_200,
    NULL as ytd_change,
    with_mas.is_volatility_index
FROM with_mas
LEFT JOIN silver.asset_registry ar ON ar.ticker = with_mas.ticker
ON CONFLICT (ticker, date) DO UPDATE SET
    open = EXCLUDED.open,
    high = EXCLUDED.high,
    low = EXCLUDED.low,
    close = EXCLUDED.close,
    volume = EXCLUDED.volume,
    change_pct = EXCLUDED.change_pct,
    change_amount = EXCLUDED.change_amount,
    ma_50 = EXCLUDED.ma_50,
    ma_200 = EXCLUDED.ma_200,
    above_ma_50 = EXCLUDED.above_ma_50,
    above_ma_200 = EXCLUDED.above_ma_200,
    updated_at = NOW();
"""

def run():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SQL)
    print(f"✅ silver.market_indices updated: {cur.rowcount} rows upserted")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
