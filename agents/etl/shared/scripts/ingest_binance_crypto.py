#!/usr/bin/env python3
"""
Binance futures klines ingestor for bronze.binance_crypto_ohlcv
Connects to AWS RDS PostgreSQL and upserts OHLCV data.

Location: ~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts/
"""
import os
import sys
import time
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

import requests
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Tickers to ingest
MAIN_TICKERS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
    "ADAUSDT", "DOGEUSDT", "LINKUSDT", "DOTUSDT", "LTCUSDT",
    "AVAXUSDT", "UNIUSDT", "ATOMUSDT", "ETCUSDT", "FILUSDT",
    "ALGOUSDT", "NEARUSDT", "APTUSDT", "ARBUSDT"
]


def get_db_conn():
    env_path = os.path.expanduser("~/.hermes/profiles/qr_etl/env/etl.env")
    load_dotenv(env_path)
    return psycopg2.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", 5432)),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        dbname=os.environ["DB_NAME"],
        sslmode="require",
        connect_timeout=15,
    )


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> List[dict]:
    url = "https://fapi.binance.com/fapi/v1/klines"
    params = {
        "symbol": symbol,
        "interval": interval,
        "startTime": start_ms,
        "endTime": end_ms,
        "limit": 1500,
    }
    all_candles = []
    while True:
        resp = requests.get(url, params=params, timeout=20)
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_candles.extend(batch)
        if len(batch) < 1500:
            break
        params["startTime"] = batch[-1][0] + 1
        time.sleep(0.05)
    return all_candles


def build_rows(candles: List[dict], ticker: str, interval: str) -> List[Tuple]:
    rows = []
    for c in candles:
        rows.append((
            ticker,
            interval,
            datetime.fromtimestamp(c[0] / 1000),
            float(c[1]),
            float(c[2]),
            float(c[3]),
            float(c[4]),
            float(c[5]),
            float(c[7]),
            int(c[8]),
            float(c[9]),
            float(c[10]),
            None,
            datetime.utcnow(),
        ))
    return rows


def get_latest_timestamp(conn, ticker: str, interval: str) -> Optional[datetime]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT max(timestamp)
        FROM bronze.binance_crypto_ohlcv
        WHERE ticker = %s AND interval = %s
        """,
        (ticker, interval),
    )
    result = cur.fetchone()[0]
    cur.close()
    return result


def ingest(interval: str, lookback_days: int):
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (lookback_days * 24 * 60 * 60 * 1000)

    conn = get_db_conn()
    total_rows = 0
    failed = []

    for ticker in MAIN_TICKERS:
        try:
            latest = get_latest_timestamp(conn, ticker, interval)
            if latest:
                fetch_start = int(latest.timestamp() * 1000) + 1
                if fetch_start >= end_ms:
                    logger.info(f"{ticker} {interval}: already up to date")
                    continue
            else:
                fetch_start = start_ms

            candles = fetch_klines(ticker, interval, fetch_start, end_ms)
            if not candles:
                logger.info(f"{ticker} {interval}: no new data")
                continue

            rows = build_rows(candles, ticker, interval)
            cur = conn.cursor()
            execute_values(
                cur,
                """
                INSERT INTO bronze.binance_crypto_ohlcv
                (ticker, interval, timestamp, open, high, low, close, volume,
                 quote_volume, trades_count, taker_buy_volume, taker_buy_quote_volume,
                 raw_data, ingested_at)
                VALUES %s
                ON CONFLICT (ticker, interval, timestamp) DO UPDATE SET
                    open = EXCLUDED.open,
                    high = EXCLUDED.high,
                    low = EXCLUDED.low,
                    close = EXCLUDED.close,
                    volume = EXCLUDED.volume,
                    quote_volume = EXCLUDED.quote_volume,
                    trades_count = EXCLUDED.trades_count,
                    taker_buy_volume = EXCLUDED.taker_buy_volume,
                    taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
                    ingested_at = EXCLUDED.ingested_at
                """,
                rows,
                page_size=1000,
            )
            conn.commit()
            cur.close()
            total_rows += len(rows)
            logger.info(f"{ticker} {interval}: upserted {len(rows)} rows")
            time.sleep(0.1)
        except Exception as e:
            logger.error(f"{ticker} {interval}: FAILED - {e}")
            failed.append(ticker)
            conn.rollback()

    conn.close()
    logger.info(f"Total upserted: {total_rows} rows | Failed: {failed}")
    return total_rows, failed


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ingest_binance_crypto.py <1h|1d> [lookback_days]")
        sys.exit(1)

    interval = sys.argv[1]
    lookback = int(sys.argv[2]) if len(sys.argv) > 2 else (90 if interval == "1h" else 365)
    ingest(interval, lookback)
