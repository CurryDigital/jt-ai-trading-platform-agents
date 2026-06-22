#!/usr/bin/env python3
"""
Register IBKR contracts for historical data fetching.
Adds liquid US equities, ETFs, and futures to bronze.ibkr_contracts.
"""
import os
import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')

import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from dotenv import load_dotenv
from ib_insync import IB, Stock, Future, Forex
import psycopg2

load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'))

DB_HOST = os.environ['DB_HOST']
DB_PORT = int(os.environ.get('DB_PORT', 5432))
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_NAME = os.environ['DB_NAME']
IBKR_PORT = int(os.environ.get('IBKR_LOCAL_TUNNEL_PORT', 14002))

# Liquid US equities for intraday strategies
EQUITIES = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'NVDA', 'META', 'SPY', 'QQQ',
    'IWM', 'XLF', 'XLK', 'XLE', 'XLI', 'XLP', 'XLU', 'XLV', 'XLB', 'XRT',
    'JPM', 'BAC', 'GS', 'MS', 'C', 'WFC',
    'JNJ', 'PFE', 'UNH', 'ABBV', 'LLY',
    'XOM', 'CVX', 'COP', 'EOG', 'SLB',
    'DIS', 'NFLX', 'CMCSA', 'T', 'VZ',
    'HD', 'WMT', 'COST', 'TGT', 'LOW',
    'BA', 'CAT', 'GE', 'HON', 'UPS',
    'V', 'MA', 'AXP', 'PYPL', 'SQ',
    'ADBE', 'CRM', 'ORCL', 'INTC', 'AMD',
    'KO', 'PEP', 'MCD', 'SBUX', 'NKE',
    'MRK', 'BMY', 'GILD', 'AMGN', 'BIIB',
    'CSCO', 'QCOM', 'AVGO', 'TXN', 'MU',
    'IBM', 'ACN', 'NOW', 'SHOP', 'UBER',
]

# Futures for commodities/indices
FUTURES = [
    ('ES', 'GLOBEX', 'USD'),   # E-mini S&P 500
    ('NQ', 'GLOBEX', 'USD'),   # E-mini Nasdaq
    ('YM', 'ECBOT', 'USD'),    # E-mini Dow
    ('CL', 'NYMEX', 'USD'),    # WTI Crude
    ('GC', 'NYMEX', 'USD'),    # Gold
    ('NG', 'NYMEX', 'USD'),    # Natural Gas
    ('ZN', 'ECBOT', 'USD'),    # 10-Year T-Note
]

# FX pairs
FX_PAIRS = [
    ('EUR', 'USD'), ('GBP', 'USD'), ('USD', 'JPY'),
    ('USD', 'CHF'), ('AUD', 'USD'), ('USD', 'CAD'), ('NZD', 'USD'),
]


def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, dbname=DB_NAME, sslmode='require'
    )


def register_contracts():
    ib = IB()
    try:
        ib.connect('127.0.0.1', IBKR_PORT, clientId=103, timeout=15)
        print(f"Connected to IBKR")
    except Exception as e:
        print(f"Connection failed: {e}")
        return

    conn = get_db_conn()
    cur = conn.cursor()
    registered = 0

    # Register equities
    for symbol in EQUITIES:
        try:
            contract = Stock(symbol, 'SMART', 'USD')
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                print(f"  Could not qualify {symbol}")
                continue
            c = qualified[0]
            cur.execute("""
                INSERT INTO bronze.ibkr_contracts (con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (con_id) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    exchange = EXCLUDED.exchange,
                    local_symbol = EXCLUDED.local_symbol,
                    trading_class = EXCLUDED.trading_class
            """, (c.conId, c.symbol, c.secType, c.exchange, c.currency, c.localSymbol, c.tradingClass))
            registered += 1
            print(f"  Registered {symbol}: conId={c.conId}")
            ib.sleep(0.5)
        except Exception as e:
            print(f"  Error {symbol}: {e}")

    # Register futures (front month)
    for symbol, exchange, currency in FUTURES:
        try:
            contract = Future(symbol, exchange=exchange, currency=currency)
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                print(f"  Could not qualify {symbol}")
                continue
            c = qualified[0]
            cur.execute("""
                INSERT INTO bronze.ibkr_contracts (con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class, expiry)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (con_id) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    exchange = EXCLUDED.exchange,
                    local_symbol = EXCLUDED.local_symbol,
                    trading_class = EXCLUDED.trading_class,
                    expiry = EXCLUDED.expiry
            """, (c.conId, c.symbol, c.secType, c.exchange, c.currency, c.localSymbol, c.tradingClass, c.lastTradeDateOrContractMonth))
            registered += 1
            print(f"  Registered {symbol}: conId={c.conId}, expiry={c.lastTradeDateOrContractMonth}")
            ib.sleep(0.5)
        except Exception as e:
            print(f"  Error {symbol}: {e}")

    # Register FX
    for base, quote in FX_PAIRS:
        try:
            pair = f"{base}{quote}"
            contract = Forex(pair)
            qualified = ib.qualifyContracts(contract)
            if not qualified:
                print(f"  Could not qualify {pair}")
                continue
            c = qualified[0]
            cur.execute("""
                INSERT INTO bronze.ibkr_contracts (con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (con_id) DO UPDATE SET
                    symbol = EXCLUDED.symbol,
                    exchange = EXCLUDED.exchange,
                    local_symbol = EXCLUDED.local_symbol,
                    trading_class = EXCLUDED.trading_class
            """, (c.conId, c.symbol, c.secType, c.exchange, c.currency, c.localSymbol, c.tradingClass))
            registered += 1
            print(f"  Registered {pair}: conId={c.conId}")
            ib.sleep(0.3)
        except Exception as e:
            print(f"  Error {pair}: {e}")

    conn.commit()
    conn.close()
    ib.disconnect()
    print(f"\nDone: {registered} contracts registered")


if __name__ == '__main__':
    register_contracts()
