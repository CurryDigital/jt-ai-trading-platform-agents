#!/usr/bin/env python3
"""
Backfill IBKR historical bars from the last existing bar up to now.

- Loads contracts from bronze.ibkr_contracts
- Fetches 1-hour and 1-minute bars in large, IBKR-safe windows
- Upserts into bronze.ibkr_historical_bars
- Reconnects automatically on disconnect / pacing error

Usage:
    python backfill_historical.py [start_YYYY-MM-DD] [end_YYYY-MM-DD]

Defaults to the day after the latest 1-hour bar in bronze.ibkr_historical_bars
through today (UTC).
"""

import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')

import asyncio
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

from dotenv import load_dotenv
from ib_insync import IB, Stock, Forex, Future
import psycopg2
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('ibkr_backfill')

ENV_PATH = os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env')
load_dotenv(ENV_PATH)

DB_HOST = os.environ['DB_HOST']
DB_PORT = int(os.environ.get('DB_PORT', 5432))
DB_USER = os.environ['DB_USER']
DB_PASSWORD = os.environ['DB_PASSWORD']
DB_NAME = os.environ['DB_NAME']

IBKR_HOST = '127.0.0.1'
IBKR_PORT = int(os.environ.get('IBKR_LOCAL_TUNNEL_PORT', 14002))

BAR_CONFIGS = [
    {'bar_size': '1 hour', 'window_days': 60, 'use_rth': True, 'what_override': None, 'sleep': 1.0},
    {'bar_size': '1 min', 'window_days': 10, 'use_rth': True, 'what_override': None, 'sleep': 2.0},
]
WHAT_TO_SHOW = 'TRADES'


# ---------------------------------------------------------------------------

def get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER,
        password=DB_PASSWORD, dbname=DB_NAME, sslmode='require'
    )


def make_contract(row):
    con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class, expiry = row
    if sec_type == 'STK':
        return Stock(symbol, exchange, currency)
    if sec_type == 'CASH':
        pair = symbol.replace('.', '').replace('/', '')
        if len(pair) != 6:
            pair = f"{symbol}{currency}" if currency else symbol
        return Forex(pair)
    if sec_type == 'FUT':
        return Future(symbol, lastTradeDateOrContractMonth=expiry, exchange=exchange, currency=currency)
    return None


def date_range(start, end, step_days):
    """Yield non-overlapping [window_start, window_end) windows that tile the range."""
    cur = start
    while cur < end:
        nxt = min(cur + timedelta(days=step_days), end)
        yield cur, nxt
        cur = nxt


def format_end_datetime(dt_utc):
    """IBKR wants endDateTime as 'YYYYMMDD-HH:MM:SS' UTC."""
    return dt_utc.strftime('%Y%m%d-%H:%M:%S')


def ensure_connected(ib, client_id):
    if not ib.isConnected():
        logger.info('Reconnecting to IBKR...')
        ib.disconnect()
        try:
            ib.connect(IBKR_HOST, IBKR_PORT, clientId=client_id, timeout=15)
            logger.info(f'Reconnected, server version {ib.client.serverVersion()}')
        except Exception as e:
            logger.error(f'Reconnect failed: {e}')
            raise


def backfill(start_date, end_date):
    ib = IB()
    ib.connect(IBKR_HOST, IBKR_PORT, clientId=200, timeout=15)
    logger.info(f'Connected to IBKR, server version {ib.client.serverVersion()}')

    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("""
        SELECT con_id, symbol, sec_type, exchange, currency, local_symbol, trading_class, NULL as expiry
        FROM bronze.ibkr_contracts
        WHERE sec_type IN ('STK', 'CASH', 'FUT')
        ORDER BY symbol
    """)
    contracts = cur.fetchall()
    logger.info(f'Found {len(contracts)} contracts to backfill from {start_date.date()} to {end_date.date()}')

    inserted_total = 0
    request_count = 0

    for row in contracts:
        con_id, symbol, sec_type = row[0], row[1], row[2]
        contract = make_contract(row)
        if not contract:
            logger.warning(f'Unknown sec_type {sec_type} for {symbol}')
            continue

        try:
            ib.qualifyContracts(contract)
        except Exception as e:
            logger.warning(f'Could not qualify {symbol}: {e}')
            continue

        for bar_config in BAR_CONFIGS:
            bar_size = bar_config['bar_size']
            window_days = bar_config['window_days']
            use_rth = bar_config['use_rth'] if sec_type == 'STK' else False
            what_to_show = bar_config['what_override'] or (WHAT_TO_SHOW if sec_type != 'CASH' else 'MIDPOINT')

            for window_start, window_end in date_range(start_date, end_date, window_days):
                ensure_connected(ib, 200 + (request_count % 100))
                request_count += 1

                # End at the close of the window
                end_dt = window_end - timedelta(minutes=1)
                end_dt = end_dt.replace(hour=23, minute=59, second=0, microsecond=0)
                end_date_str = format_end_datetime(end_dt)
                duration_str = f'{window_days} D'

                try:
                    bars = ib.reqHistoricalData(
                        contract,
                        endDateTime=end_date_str,
                        durationStr=duration_str,
                        barSizeSetting=bar_size,
                        whatToShow=what_to_show,
                        useRTH=use_rth,
                        formatDate=1
                    )
                except Exception as e:
                    logger.error(f'Error fetching {symbol} {bar_size} ending {end_date_str}: {e}')
                    ib.disconnect()
                    ib.sleep(2)
                    continue

                if bars is None or not bars:
                    logger.warning(f'No bars for {symbol} {bar_size} ending {end_date_str}')
                    ib.sleep(1.0)
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
                    rows.append((
                        con_id, bar_time, bar.open, bar.high, bar.low, bar.close,
                        int(bar.volume or 0), bar_size, what_to_show
                    ))

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
                logger.info(f'{symbol} {bar_size} ending {end_date_str}: {len(rows)} bars (total upserted {inserted_total})')
                ib.sleep(bar_config.get('sleep', 1.5))

    cur.close()
    conn.close()
    ib.disconnect()
    logger.info(f'Backfill complete: {inserted_total} total bars upserted, {request_count} requests')


if __name__ == '__main__':
    if len(sys.argv) >= 3:
        start_date = datetime.strptime(sys.argv[1], '%Y-%m-%d').replace(tzinfo=timezone.utc)
        end_date = datetime.strptime(sys.argv[2], '%Y-%m-%d').replace(tzinfo=timezone.utc) + timedelta(days=1)
    else:
        conn = get_db_conn()
        c = conn.cursor()
        c.execute("SELECT MAX(bar_time) FROM bronze.ibkr_historical_bars WHERE bar_size = '1 hour'")
        last = c.fetchone()[0]
        c.close(); conn.close()
        if last is None:
            start_date = datetime(2026, 1, 1, tzinfo=timezone.utc)
        else:
            start_date = datetime(last.year, last.month, last.day, tzinfo=timezone.utc) + timedelta(days=1)
        end_date = datetime.now(timezone.utc) + timedelta(days=1)
    backfill(start_date, end_date)
