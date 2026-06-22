#!/usr/bin/env python3
"""
Silver Layer — Crypto Normalization (DB-aware version)
Reads from bronze.binance_crypto_ohlcv (DB) and upserts to silver.crypto_ohlcv_normalized
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('crypto_silver')

SCRIPT_DIR = Path(__file__).parent
WORKSPACE = SCRIPT_DIR.parent
SILVER_DIR = WORKSPACE / 'silver' / 'crypto'

ENV_FILE = Path('/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env')
load_dotenv(ENV_FILE)


def get_db_conn():
    return psycopg2.connect(
        host=os.environ['DB_HOST'],
        port=int(os.environ.get('DB_PORT', 5432)),
        user=os.environ['DB_USER'],
        password=os.environ['DB_PASSWORD'],
        dbname=os.environ['DB_NAME'],
        sslmode='require',
        connect_timeout=15,
    )


def load_bronze_data():
    """Load bronze crypto data directly from PostgreSQL"""
    conn = get_db_conn()
    logger.info("Querying bronze.binance_crypto_ohlcv from DB...")

    # Get last 90 days of data for normalization
    query = """
        SELECT
            ticker AS symbol,
            interval,
            timestamp,
            open,
            high,
            low,
            close,
            volume,
            quote_volume,
            trades_count AS trades,
            taker_buy_volume AS taker_buy_base,
            taker_buy_quote_volume AS taker_buy_quote
        FROM bronze.binance_crypto_ohlcv
        WHERE timestamp >= NOW() - INTERVAL '90 days'
        ORDER BY ticker, interval, timestamp
    """
    df = pd.read_sql(query, conn)
    conn.close()

    if df.empty:
        logger.warning("No bronze data found in DB for last 90 days")
        return None

    logger.info(f"Loaded {len(df)} rows from bronze.binance_crypto_ohlcv")
    return df


def normalize_crypto(df):
    """
    Normalize crypto data to standard schema:
    - Standard column names (open, high, low, close, volume)
    - Add derived metrics (returns, volatility, vwap)
    - Remove duplicates
    - Sort by timestamp
    """
    logger.info("Normalizing crypto data...")

    # Select and rename columns
    normalized = df[[
        'timestamp', 'symbol', 'interval', 'open', 'high', 'low', 'close',
        'volume', 'quote_volume', 'trades', 'taker_buy_base', 'taker_buy_quote'
    ]].copy()

    # Ensure proper sorting
    normalized = normalized.sort_values(['symbol', 'interval', 'timestamp'])

    # Remove duplicates (same symbol + interval + timestamp)
    before_dedup = len(normalized)
    normalized = normalized.drop_duplicates(subset=['symbol', 'interval', 'timestamp'])
    after_dedup = len(normalized)
    if before_dedup != after_dedup:
        logger.warning(f"Removed {before_dedup - after_dedup} duplicate rows")

    # Calculate derived metrics per symbol/interval group
    results = []
    for (symbol, interval), group in normalized.groupby(['symbol', 'interval']):
        group = group.copy()

        # Calculate returns
        group['returns'] = group['close'].pct_change()

        # Calculate log returns
        group['log_returns'] = np.log(group['close'] / group['close'].shift(1))

        # Calculate VWAP (Volume Weighted Average Price)
        group['vwap'] = (group['close'] * group['volume']).cumsum() / group['volume'].cumsum()

        # Calculate rolling volatility (20-period std of returns)
        group['volatility_20'] = group['returns'].rolling(window=20, min_periods=5).std()

        # True Range and ATR
        group['tr1'] = group['high'] - group['low']
        group['tr2'] = abs(group['high'] - group['close'].shift(1))
        group['tr3'] = abs(group['low'] - group['close'].shift(1))
        group['true_range'] = group[['tr1', 'tr2', 'tr3']].max(axis=1)
        group['atr_14'] = group['true_range'].rolling(window=14, min_periods=5).mean()

        # Drop temp columns
        group = group.drop(['tr1', 'tr2', 'tr3'], axis=1)

        # Market cap proxy (using quote volume as indicator)
        group['market_cap_proxy'] = group['close'] * group['volume']

        # Add metadata
        group['normalized_at'] = datetime.utcnow()
        group['data_source'] = 'binance'

        results.append(group)

    final_df = pd.concat(results, ignore_index=True)
    logger.info(f"Normalization complete: {len(final_df)} rows")
    return final_df


def upsert_to_db(df):
    """Upsert normalized data to silver.crypto_ohlcv_normalized"""
    if df.empty:
        logger.warning("No data to upsert")
        return 0

    conn = get_db_conn()
    cur = conn.cursor()

    # Prepare data tuples
    rows = []
    for _, row in df.iterrows():
        rows.append((
            row['symbol'],
            row['interval'],
            row['timestamp'],
            row['open'],
            row['high'],
            row['low'],
            row['close'],
            row['volume'],
            row['quote_volume'],
            int(row['trades']) if pd.notna(row['trades']) else None,
            row['taker_buy_base'],
            row['taker_buy_quote'],
            row['returns'],
            row['log_returns'],
            row['vwap'],
            row['volatility_20'],
            row['true_range'],
            row['atr_14'],
            row['market_cap_proxy'],
            row['data_source'],
            row['normalized_at']
        ))

    # Upsert query
    upsert_sql = """
        INSERT INTO silver.crypto_ohlcv_normalized (
            symbol, interval, timestamp, open, high, low, close,
            volume, quote_volume, trades_count, taker_buy_volume, taker_buy_quote_volume,
            returns, log_returns, vwap, volatility_20, true_range, atr_14,
            market_cap_proxy, data_source, normalized_at
        ) VALUES %s
        ON CONFLICT (symbol, interval, timestamp) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            quote_volume = EXCLUDED.quote_volume,
            trades_count = EXCLUDED.trades_count,
            taker_buy_volume = EXCLUDED.taker_buy_volume,
            taker_buy_quote_volume = EXCLUDED.taker_buy_quote_volume,
            returns = EXCLUDED.returns,
            log_returns = EXCLUDED.log_returns,
            vwap = EXCLUDED.vwap,
            volatility_20 = EXCLUDED.volatility_20,
            true_range = EXCLUDED.true_range,
            atr_14 = EXCLUDED.atr_14,
            market_cap_proxy = EXCLUDED.market_cap_proxy,
            data_source = EXCLUDED.data_source,
            normalized_at = EXCLUDED.normalized_at
    """

    execute_values(cur, upsert_sql, rows, page_size=1000)
    conn.commit()
    cur.close()
    conn.close()

    logger.info(f"Upserted {len(rows)} rows to silver.crypto_ohlcv_normalized")
    return len(rows)


def save_silver(df, date_str):
    """Save normalized data to silver layer (parquet + DB)"""
    SILVER_DIR.mkdir(parents=True, exist_ok=True)

    # Check if pyarrow is available
    try:
        import pyarrow  # noqa: F401
        has_parquet = True
    except ImportError:
        has_parquet = False
        logger.warning("pyarrow not available — skipping parquet writes")

    if has_parquet:
        # Save by symbol for efficient querying
        for symbol in df['symbol'].unique():
            symbol_df = df[df['symbol'] == symbol].copy()

            # Save each interval separately
            for interval in symbol_df['interval'].unique():
                interval_df = symbol_df[symbol_df['interval'] == interval].copy()

                filename = f"{symbol}_{interval}_{date_str}.parquet"
                output_path = SILVER_DIR / filename

                interval_df.to_parquet(output_path, index=False)
                logger.info(f"Saved {symbol} {interval}: {len(interval_df)} rows → {output_path}")

        # Also save combined file for cross-asset analysis
        combined_path = SILVER_DIR / f'crypto_combined_{date_str}.parquet'
        df.to_parquet(combined_path, index=False)
        logger.info(f"Saved combined file: {len(df)} rows → {combined_path}")
        return combined_path
    else:
        # Save as CSV fallback
        combined_path = SILVER_DIR / f'crypto_combined_{date_str}.csv'
        df.to_csv(combined_path, index=False)
        logger.info(f"Saved combined CSV: {len(df)} rows → {combined_path}")
        return combined_path


def main():
    """Main silver layer routine"""
    logger.info("=" * 50)
    logger.info("Crypto Silver Normalization Started")
    logger.info("=" * 50)

    # Use yesterday's date if running before market close
    date_str = (datetime.utcnow() - timedelta(days=0)).strftime('%Y%m%d')

    # Load bronze data from DB
    bronze_df = load_bronze_data()
    if bronze_df is None:
        logger.error("No bronze data to process")
        return 1

    # Normalize
    normalized_df = normalize_crypto(bronze_df)

    # Save to silver (parquet files)
    save_silver(normalized_df, date_str)

    # Upsert to DB
    upsert_to_db(normalized_df)

    # Write summary
    summary = {
        'date': date_str,
        'source': 'binance',
        'bronze_rows': len(bronze_df),
        'silver_rows': len(normalized_df),
        'symbols': sorted(normalized_df['symbol'].unique().tolist()),
        'intervals': sorted(normalized_df['interval'].unique().tolist()),
        'timestamp': datetime.utcnow().isoformat()
    }

    summary_path = SILVER_DIR / f'summary_{date_str}.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    logger.info("=" * 50)
    logger.info(f"Silver normalization complete: {len(normalized_df)} rows")
    logger.info(f"Symbols: {len(summary['symbols'])}")
    logger.info("=" * 50)

    return 0


if __name__ == '__main__':
    exit(main())
