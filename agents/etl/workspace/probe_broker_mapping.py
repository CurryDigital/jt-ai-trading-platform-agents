#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

hk_tickers = [
    "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK", "0011.HK",
    "0016.HK", "0027.HK", "0388.HK", "0669.HK", "0836.HK", "0939.HK",
    "0941.HK", "1038.HK", "1299.HK", "1398.HK", "1928.HK", "2318.HK",
    "2388.HK", "2628.HK", "2800.HK", "AGG",
]
ibkr_symbols = [ticker.replace(".HK", "").lstrip("0") or "0" for ticker in hk_tickers if ticker.endswith(".HK")]
ibkr_symbols.append("AGG")

conn = get_connection()
cur = conn.cursor()
print("--- bronze.ibkr_contracts rows for HK tickers ---")
cur.execute(
    """
    SELECT con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class
    FROM bronze.ibkr_contracts
    WHERE symbol = ANY(%s) OR local_symbol = ANY(%s)
    ORDER BY symbol;
    """,
    (hk_tickers, ibkr_symbols),
)
rows = cur.fetchall()
for r in rows:
    print(f"con_id={r[0]} symbol={r[1]} sec_type={r[2]} exchange={r[3]} currency={r[4]} local_symbol={r[5]} trading_class={r[6]}")
found_symbols = {r[1] for r in rows}
missing = [t for t in hk_tickers if t not in found_symbols]
print(f"\nfound={len(found_symbols)} missing={len(missing)}")
if missing:
    print("missing tickers:", missing)
conn.close()
