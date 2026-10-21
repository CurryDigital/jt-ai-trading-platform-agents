#!/usr/bin/env python3
"""
One-off backfill (kanban t_464bcdb1): full-history yfinance backfill for the
15 '=X' FX pairs into bronze.yf_prices.

Root cause: gold.asset_registry lists these pairs with asset_class='FX'
(JPY=X as 'CURRENCY'), which ingest_yfinance_prices.get_active_tickers()
excluded (filter was STOCK/ETF/INDEX only) — no daily ingest since
registration; silver.unified_prices froze at 2026-02-27.

The ingest filter is patched in the same task; this script is the catch-up.
Reuses ingest_yf_prices() so the load path (batch upsert, sanity gate,
row-error accounting) is identical to the daily run.

Run from agents/etl:  python workspace/oneoff/backfill_fx_yf_2026-08-06.py
"""
import os
import sys

ETL_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
sys.path.insert(0, os.path.join(ETL_ROOT, 'bronze', 'yfinance'))
os.chdir(ETL_ROOT)

from ingest_yfinance_prices import ingest_yf_prices, _check_row_error_rate

FX_TICKERS = [
    'AUDJPY=X', 'AUDUSD=X', 'CADJPY=X', 'CHFJPY=X', 'EURAUD=X',
    'EURCHF=X', 'EURGBP=X', 'EURJPY=X', 'EURUSD=X', 'GBPAUD=X',
    'GBPJPY=X', 'GBPUSD=X', 'JPY=X', 'NZDUSD=X', 'USDCAD=X',
    'USDCHF=X', 'USDHKD=X', 'USDJPY=X',
]

if __name__ == '__main__':
    # ~9.5 years covers the full silver history (~2017-12) plus margin.
    ingest_yf_prices(tickers=FX_TICKERS, days_back=3500)
    _check_row_error_rate()
