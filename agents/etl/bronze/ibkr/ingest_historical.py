#!/usr/bin/env python3
"""
IBKR Historical Bars Ingestion Pipeline
Fetches 1-hour and 1-minute bars from TWS API and stores in bronze.ibkr_historical_bars
"""

import os
import sys
import logging
from datetime import datetime

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')

import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from dotenv import load_dotenv
from ib_insync import IB, Stock, Forex, Future, util

import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('ibkr_historical')

ENV_PATH = os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env')
load_dotenv(ENV_PATH)

DB_HOST = os.environ['DB_HOST']
DB_PORT = int(os.environ.get('DB_PORT', 5432))
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_NAME = os.environ['DB_NAME']

IBKR_PORT = int(os.environ.get('IBKR_LOCAL_TUNNEL_PORT', 14002))

# Configurable bar sizes
BAR_CONFIGS = [
    {'bar_size': '1 hour', 'duration': '5 D'},
    {'bar_size': '1 min', 'duration': '1 D'},
]
WHAT_TO_SHOW = 'TRADES'
USE_RTH = True


def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, dbname=DB_NAME, sslmode='require'
    )


def make_contract(row):
    """Build ib_insync contract from DB row."""
    con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class, expiry = row
    if sec_type == 'STK':
        return Stock(symbol, exchange, currency)
    elif sec_type == 'CASH':
        # Forex expects 6-char pair like EURUSD
        pair = symbol.replace('.', '').replace('/', '')
        if len(pair) != 6:
            pair = f"{symbol}{currency}" if currency else symbol
        return Forex(pair)
    elif sec_type == 'FUT':
        return Future(symbol, lastTradeDateOrContractMonth=expiry, exchange=exchange, currency=currency)
    else:
        return None


def ingest_historical():
    ib = IB()
    try:
        ib.connect('127.0.0.1', IBKR_PORT, clientId=102, timeout=15)
        logger.info(f"Connected to IBKR, server version {ib.client.serverVersion()}")
    except Exception as e:
        logger.error(f"Connection failed: {e}")
        return

    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class, NULL as expiry
        FROM bronze.ibkr_contracts
        WHERE sec_type IN ('STK', 'CASH', 'FUT')
        ORDER BY symbol
    """)
    contracts = cur.fetchall()
    logger.info(f"Found {len(contracts)} contracts to fetch")

    inserted_total = 0
    for row in contracts:
        con_id, symbol, sec_type = row[0], row[1], row[2]
        contract = make_contract(row)
        if not contract:
            logger.warning(f"Unknown sec_type {sec_type} for {symbol}")
            continue

        for bar_config in BAR_CONFIGS:
            bar_size = bar_config['bar_size']
            duration = bar_config['duration']
            try:
                ib.qualifyContracts(contract)

                bars = ib.reqHistoricalData(
                    contract,
                    endDateTime='',
                    durationStr=duration,
                    barSizeSetting=bar_size,
                    whatToShow=WHAT_TO_SHOW if sec_type != 'CASH' else 'MIDPOINT',
                    useRTH=USE_RTH if sec_type == 'STK' else False,
                    formatDate=1
                )

                if bars is None:
                    logger.warning(f"Timeout for {symbol} {bar_size}")
                    continue
                if not bars:
                    logger.warning(f"No bars for {symbol} {bar_size}")
                    continue

                rows = []
                for bar in bars:
                    if isinstance(bar.date, str):
                        if ' ' in bar.date:
                            bar_time = datetime.strptime(bar.date, '%Y%m%d %H:%M:%S')
                        else:
                            bar_time = datetime.strptime(bar.date, '%Y%m%d')
                    else:
                        bar_time = bar.date.replace(tzinfo=None)
                    rows.append((con_id, bar_time, bar.open, bar.high, bar.low, bar.close, int(bar.volume or 0), bar_size, WHAT_TO_SHOW if sec_type != 'CASH' else 'MIDPOINT'))

                execute_values(cur, """
                    INSERT INTO bronze.ibkr_historical_bars
                    (con_id, bar_time, open, high, low, close, volume, bar_size, what_to_show)
                    VALUES %s
                    ON CONFLICT (con_id, bar_time, bar_size, what_to_show) DO UPDATE SET
                        open = EXCLUDED.open,
                        high = EXCLUDED.high,
                        low = EXCLUDED.low,
                        close = EXCLUDED.close,
                        volume = EXCLUDED.volume,
                        created_at = NOW()
                """, rows)
                conn.commit()
                inserted_total += len(rows)
                logger.info(f"{symbol} {bar_size}: {len(rows)} bars inserted")
                ib.sleep(1.5)

            except AssertionError as e:
                logger.warning(f"AssertionError for {symbol} {bar_size}, reconnecting...")
                ib.disconnect()
                ib.sleep(2)
                try:
                    ib.connect('127.0.0.1', IBKR_PORT, clientId=102, timeout=15)
                except Exception:
                    pass
            except Exception as e:
                logger.error(f"Error fetching {symbol} {bar_size}: {e}")

    cur.close()
    conn.close()
    ib.disconnect()
    logger.info(f"Done: {inserted_total} total bars inserted")




def _mark_freshness(error=None):
    """Update gold.source_freshness for the operator dashboard. Soft-fails."""
    try:
        from db import get_connection
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(conn, source='ibkr', error=error)
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")

if __name__ == '__main__':
    try:
        ingest_historical()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
