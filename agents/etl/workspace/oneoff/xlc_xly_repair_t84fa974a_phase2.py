#!/usr/bin/env python3
"""Phase 2 — t_84fa974a: bronze ingest via canonical ingest_yf_prices path.

XLC: days_back=3080 -> start ~2018-06-05, covers inception 2018-06-18; Yahoo
serves nothing pre-inception (no fabricated rows possible).
XLY: days_back=167 -> start 2026-05-19, the first session AFTER the existing
silver tail (2026-05-18). Zero overlap with pre-existing rows => zero
restatement of research-consumed history.
"""
import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl'))
from bronze.yfinance.ingest_yfinance_prices import ingest_yf_prices
from datetime import date, timedelta

print('XLC start will be:', date.today() - timedelta(days=3080))
print('XLY start will be:', date.today() - timedelta(days=167))

print('=== XLC full history ===')
ingest_yf_prices(tickers=['XLC'], days_back=3080)
print('=== XLY repair window ===')
ingest_yf_prices(tickers=['XLY'], days_back=167)
print('PHASE2 OK')
