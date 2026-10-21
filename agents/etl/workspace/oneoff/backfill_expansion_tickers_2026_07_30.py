#!/usr/bin/env python3
"""
One-off (kanban t_cf9c5c8b): bronze yfinance backfill for 26 expansion tickers.
Pulls 2019-01-01 -> today (matches deepest existing peers: GLD/IWM/SPY).
Funds with later inception simply start later.
"""
import sys, os
ETL = '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl'
os.chdir(ETL)
sys.path.insert(0, os.path.join(ETL, 'shared', 'scripts'))
sys.path.insert(0, os.path.join(ETL, 'bronze', 'yfinance'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from datetime import date
import ingest_yfinance_prices as ing

TICKERS = ['DIVO','RYLD','IJR','VB','SCHA','VTWO','SJNK','USHY','VCIT','BKLN',
           'SDY','NOBL','DVY','USMV','VIG','IAU','GLDM','SGOL',
           '2828.HK','ASHR','MCHI','FXI','3115.HK','IJH','MDY','FXE']

days_back = (date.today() - date(2019, 1, 1)).days
print(f"Backfilling {len(TICKERS)} tickers, days_back={days_back}")
ing.ingest_yf_prices(tickers=TICKERS, days_back=days_back)
print(f"row errors: {ing._n_row_errors} / {ing._n_rows_attempted}")
