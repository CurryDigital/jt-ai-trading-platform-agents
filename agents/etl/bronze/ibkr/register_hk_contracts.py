#!/usr/bin/env python3
"""
Register HK equity and ETF contracts in bronze.ibkr_contracts for the
HK strategy expansion batch (2 strategies).

Uses ibapi (included in ETL venv) and connects to the local IBKR TWS API
tunnel on 127.0.0.1:14002.

Tickers mapped:
- 2800.HK  -> 2800  (Hang Seng ETF)
- 0001.HK  -> 1     (CK Hutchison)
- 0002.HK  -> 2     (CLP Holdings)
- 0003.HK  -> 3     (HK & China Gas)
- 0005.HK  -> 5     (HSBC)
- 0006.HK  -> 6     (Power Assets)
- 0011.HK  -> 11    (Hang Seng Bank)
- 0016.HK  -> 16    (Sinopec Kantons)
- 0027.HK  -> 27    (Galaxy Entertainment)
- 0388.HK  -> 388   (HKEx)
- 0669.HK  -> 669   (Techtronic Industries)
- 0836.HK  -> 836   (China Resources Power)
- 0939.HK  -> 939   (CCB)
- 0941.HK  -> 941   (China Mobile)
- 1038.HK  -> 1038  (CK Infrastructure)
- 1299.HK  -> 1299  (AIA)
- 1398.HK  -> 1398  (ICBC)
- 1928.HK  -> 1928  (Sands China)
- 2318.HK  -> 2318  (Ping An)
- 2388.HK  -> 2388  (BOC Hong Kong)
- 2628.HK  -> 2628  (China Life)
- AGG      -> AGG   (US AGG ETF, SMART/USD)

Operational notes:
- Read-only / contract-qualification only; no orders placed.
- Idempotent: ON CONFLICT (con_id) DO UPDATE.
- If IBKR connection fails, the script exits non-zero with a clear error.
"""
import os
import sys
import time
import threading

from dotenv import load_dotenv
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract
import psycopg2

load_dotenv(os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env'))

DB_HOST = os.environ['DB_HOST']
DB_PORT = int(os.environ.get('DB_PORT', 5432))
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_NAME = os.environ['DB_NAME']
IBKR_HOST = os.environ.get('IBKR_HOST', '127.0.0.1')
IBKR_PORT = int(os.environ.get('IBKR_PORT', 14002))

# (yfinance ticker, IBKR symbol, exchange, currency)
TICKERS = [
    ("2800.HK", "2800", "SEHK", "HKD"),
    ("0001.HK", "1", "SEHK", "HKD"),
    ("0002.HK", "2", "SEHK", "HKD"),
    ("0003.HK", "3", "SEHK", "HKD"),
    ("0005.HK", "5", "SEHK", "HKD"),
    ("0006.HK", "6", "SEHK", "HKD"),
    ("0011.HK", "11", "SEHK", "HKD"),
    ("0016.HK", "16", "SEHK", "HKD"),
    ("0027.HK", "27", "SEHK", "HKD"),
    ("0388.HK", "388", "SEHK", "HKD"),
    ("0669.HK", "669", "SEHK", "HKD"),
    ("0700.HK", "700", "SEHK", "HKD"),
    ("0836.HK", "836", "SEHK", "HKD"),
    ("0939.HK", "939", "SEHK", "HKD"),
    ("0941.HK", "941", "SEHK", "HKD"),
    ("1038.HK", "1038", "SEHK", "HKD"),
    ("1299.HK", "1299", "SEHK", "HKD"),
    ("1398.HK", "1398", "SEHK", "HKD"),
    ("1928.HK", "1928", "SEHK", "HKD"),
    ("2318.HK", "2318", "SEHK", "HKD"),
    ("2388.HK", "2388", "SEHK", "HKD"),
    ("2628.HK", "2628", "SEHK", "HKD"),
    ("AGG", "AGG", "SMART", "USD"),
]


class IBWrapper(EWrapper):
    def __init__(self):
        self.connected = threading.Event()
        self.details = {}
        self.errors = {}
        self.end = {}

    def nextValidId(self, orderId):
        self.connected.set()

    def contractDetails(self, reqId, contractDetails):
        self.details[reqId] = contractDetails.contract

    def contractDetailsEnd(self, reqId):
        self.end[reqId] = True

    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=None):
        if errorCode in (0, 2104, 2106, 2107, 2108):
            return
        self.errors[reqId] = (errorCode, errorString)


def make_contract(symbol, exchange, currency, sec_type='STK'):
    c = Contract()
    c.symbol = symbol
    c.secType = sec_type
    c.exchange = exchange
    c.currency = currency
    return c


def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, dbname=DB_NAME, sslmode='require'
    )


def register():
    wrapper = IBWrapper()
    client = EClient(wrapper)

    print(f"Connecting to IBKR at {IBKR_HOST}:{IBKR_PORT} ...")
    client.connect(IBKR_HOST, IBKR_PORT, clientId=105)
    thread = threading.Thread(target=client.run, daemon=True)
    thread.start()

    if not wrapper.connected.wait(timeout=15):
        print(f"ERROR: cannot connect to IBKR at {IBKR_HOST}:{IBKR_PORT} (no nextValidId)")
        client.disconnect()
        sys.exit(1)
    print("Connected to IBKR")

    conn = get_db_conn()
    cur = conn.cursor()
    registered = 0
    failed = []
    req_id = 1

    for yf_ticker, ibkr_symbol, exchange, currency in TICKERS:
        contract = make_contract(ibkr_symbol, exchange, currency)
        client.reqContractDetails(req_id, contract)

        for _ in range(100):
            if req_id in wrapper.end or req_id in wrapper.errors:
                break
            time.sleep(0.1)

        if req_id in wrapper.details:
            c = wrapper.details[req_id]
            cur.execute(
                """
                INSERT INTO bronze.ibkr_contracts
                  (con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (con_id) DO UPDATE SET
                  symbol = EXCLUDED.symbol,
                  exchange = EXCLUDED.exchange,
                  local_symbol = EXCLUDED.local_symbol,
                  trading_class = EXCLUDED.trading_class;
                """,
                (c.conId, yf_ticker, c.secType, c.exchange, c.currency, c.localSymbol, c.tradingClass)
            )
            registered += 1
            print(f"  Registered {yf_ticker} -> IBKR {c.symbol} (con_id={c.conId}, local_symbol={c.localSymbol}, exchange={c.exchange})")
        elif req_id in wrapper.errors:
            failed.append((yf_ticker, wrapper.errors[req_id]))
            print(f"  ERROR {yf_ticker}: code={wrapper.errors[req_id][0]} msg={wrapper.errors[req_id][1]}")
        else:
            failed.append((yf_ticker, "timeout"))
            print(f"  WARN {yf_ticker}: no response within 10s")

        req_id += 1
        time.sleep(0.5)

    conn.commit()
    conn.close()
    client.disconnect()

    print(f"\nDone: {registered}/{len(TICKERS)} contracts registered")
    if failed:
        print(f"Failed: {failed}")
        sys.exit(2)


if __name__ == '__main__':
    register()
