# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Layer — Crypto Metrics Curation
Builds curated crypto metrics from bronze.binance_crypto_ohlcv for consumption

Writes to: gold.crypto_metrics (DB table)
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('crypto_gold')

SCRIPT_DIR = Path(__file__).parent
WORKSPACE = SCRIPT_DIR.parent.parent
GOLD_DIR = WORKSPACE / 'gold' / 'crypto'

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
            taker_buy_volume,
            taker_buy_quote_volume
        FROM bronze.binance_crypto_ohlcv
        WHERE interval = '1d'
          AND timestamp >= NOW() - INTERVAL '90 days'
        ORDER BY ticker, timestamp
    """
    df = pd.read_sql(query, conn)
    conn.close()

    if df.empty:
        logger.warning("No daily bronze data found in DB")
        return None

    logger.info(f"Loaded {len(df)} rows from bronze.binance_crypto_ohlcv")
    return df


def calculate_metrics(df):
    """
    Calculate gold-layer metrics for crypto assets:
    - Daily metrics (for 1d interval data)
    - Risk metrics (volatility, sharpe, max drawdown)
    - Momentum indicators (RSI, MACD)
    - Volume metrics
    """
    logger.info("Calculating gold-layer metrics...")

    results = []

    for symbol, group in df.groupby('symbol'):
        group = group.sort_values('timestamp').copy()

        # Price metrics
        group['price_sma_7'] = group['close'].rolling(window=7, min_periods=3).mean()
        group['price_sma_30'] = group['close'].rolling(window=30, min_periods=10).mean()

        # RSI calculation
        delta = group['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=14, min_periods=5).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=14, min_periods=5).mean()
        rs = gain / loss
        group['rsi_14'] = 100 - (100 / (1 + rs))

        # MACD
        ema_12 = group['close'].ewm(span=12, min_periods=5).mean()
        ema_26 = group['close'].ewm(span=26, min_periods=10).mean()
        group['macd'] = ema_12 - ema_26
        group['macd_signal'] = group['macd'].ewm(span=9, min_periods=3).mean()
        group['macd_histogram'] = group['macd'] - group['macd_signal']

        # Bollinger Bands
        group['bb_middle'] = group['close'].rolling(window=20, min_periods=5).mean()
        bb_std = group['close'].rolling(window=20, min_periods=5).std()
        group['bb_upper'] = group['bb_middle'] + (bb_std * 2)
        group['bb_lower'] = group['bb_middle'] - (bb_std * 2)
        group['bb_width'] = (group['bb_upper'] - group['bb_lower']) / group['bb_middle']

        # Volume metrics
        group['volume_sma_20'] = group['volume'].rolling(window=20, min_periods=5).mean()
        group['volume_ratio'] = group['volume'] / group['volume_sma_20']

        # Returns
        group['returns'] = group['close'].pct_change()
        group['cumulative_return'] = (1 + group['returns']).cumprod() - 1

        # Max drawdown
        rolling_max = group['close'].cummax()
        drawdown = (group['close'] - rolling_max) / rolling_max
        group['max_drawdown'] = drawdown

        # Rolling sharpe (annualized, 30-day window)
        group['sharpe_30'] = (
            group['returns'].rolling(window=30, min_periods=10).mean() * 365 /
            (group['returns'].rolling(window=30, min_periods=10).std() * np.sqrt(365))
        )

        # Volatility
        group['volatility_20d'] = group['returns'].rolling(window=20, min_periods=5).std() * np.sqrt(365)

        results.append(group)

    final_df = pd.concat(results, ignore_index=True)
    logger.info(f"Metrics calculated: {len(final_df)} rows")
    return final_df


def prepare_for_gold_schema(df):
    """Map to existing gold.crypto_metrics schema"""
    logger.info("Mapping to gold.crypto_metrics schema...")

    gold_df = pd.DataFrame()
    gold_df['date'] = pd.to_datetime(df['timestamp'])
    gold_df['ticker'] = df['symbol']
    gold_df['close_price'] = df['close']
    gold_df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    gold_df['volume_24h'] = df['volume'].clip(upper=9223372036854775807).astype('int64')
    gold_df['market_cap_usd'] = df['close'] * df['volume']
    gold_df['btc_dominance'] = np.nan
    gold_df['eth_gas_price_gwei'] = np.nan
    gold_df['hash_rate_th_s'] = np.nan
    gold_df['exchange_inflow_proxy'] = np.nan
    gold_df['exchange_outflow_proxy'] = np.nan
    gold_df['fear_greed_index'] = np.nan
    gold_df['stablecoin_supply_ratio'] = np.nan
    gold_df['funding_rate'] = np.nan
    gold_df['open_interest_usd'] = np.nan
    gold_df['liquidations_24h_usd'] = np.nan
    gold_df['rsi_14'] = df['rsi_14']
    gold_df['macd_histogram'] = df['macd_histogram']
    gold_df['bollinger_width'] = df['bb_width']
    gold_df['mvrv_z_score'] = np.nan
    gold_df['nvt_ratio'] = np.nan
    gold_df['prophet_forecast'] = np.nan
    gold_df['lsd_divergence_score'] = np.nan
    gold_df['candlestick_pattern'] = None
    gold_df['candlestick_sentiment'] = np.nan

    # Drop rows with NaN in critical columns
    gold_df = gold_df.dropna(subset=['date', 'ticker', 'close_price'])

    # Fix: integer columns with NaN must be object dtype with None for psycopg2
    for col in ['volume_24h', 'fear_greed_index']:
        if col in gold_df.columns:
            gold_df[col] = gold_df[col].astype(object).where(pd.notna(gold_df[col]), None)

    return gold_df


def upsert_to_db(df):
    """Upsert into gold.crypto_metrics"""
    conn = get_db_conn()
    cur = conn.cursor()

    # Check table exists
    cur.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'gold' AND table_name = 'crypto_metrics'
        );
    """)
    if not cur.fetchone()[0]:
        logger.error("gold.crypto_metrics does not exist")
        conn.close()
        return

    # Delete existing rows for these tickers/dates to avoid conflicts
    # (since there's no proper PK on this table)
    tickers = df['ticker'].unique().tolist()
    min_date = df['date'].min()
    max_date = df['date'].max()

    cur.execute("""
        DELETE FROM gold.crypto_metrics
        WHERE ticker = ANY(%s)
          AND date >= %s
          AND date <= %s;
    """, (tickers, min_date, max_date))
    logger.info(f"Deleted {cur.rowcount} existing rows for overlap tickers/dates")

    # Insert
    from psycopg2.extras import execute_values
    cols = list(df.columns)
    rows = [tuple(row) for _, row in df.iterrows()]

    execute_values(cur, f"""
        INSERT INTO gold.crypto_metrics ({', '.join(cols)})
        VALUES %s;
    """, rows, page_size=1000)

    conn.commit()
    logger.info(f"Inserted {len(rows)} rows into gold.crypto_metrics")
    cur.close()
    conn.close()


def save_gold(df, date_str):
    """Save gold layer data to parquet (for backward compatibility)"""
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    output_path = GOLD_DIR / f'crypto_metrics_{date_str}.parquet'

    # Check if pyarrow is available
    try:
        import pyarrow  # noqa: F401
        df.to_parquet(output_path, index=False)
        logger.info(f"Saved gold metrics: {len(df)} rows → {output_path}")
    except ImportError:
        # Save as CSV fallback
        csv_path = GOLD_DIR / f'crypto_metrics_{date_str}.csv'
        df.to_csv(csv_path, index=False)
        logger.info(f"Saved gold metrics CSV: {len(df)} rows → {csv_path}")

    return output_path


def main():
    """Main gold layer routine"""
    logger.info("=" * 50)
    logger.info("Crypto Gold Curation Started")
    logger.info("=" * 50)

    date_str = datetime.utcnow().strftime('%Y%m%d')

    # Load bronze data from DB
    bronze_df = load_bronze_data()
    if bronze_df is None:
        logger.error("No bronze data to process")
        return 1

    # Calculate metrics
    metrics_df = calculate_metrics(bronze_df)
    if metrics_df is None or metrics_df.empty:
        logger.error("Failed to calculate metrics")
        return 1

    # Prepare for gold schema
    gold_df = prepare_for_gold_schema(metrics_df)

    # Upsert to DB
    upsert_to_db(gold_df)

    # Save parquet for backward compatibility
    save_gold(gold_df, date_str)

    # Summary
    summary = {
        'date': date_str,
        'source': 'binance',
        'bronze_rows': len(bronze_df),
        'gold_rows': len(gold_df),
        'symbols': sorted(gold_df['ticker'].unique().tolist()),
        'timestamp': datetime.utcnow().isoformat()
    }

    summary_path = GOLD_DIR / f'summary_{date_str}.json'
    with open(summary_path, 'w') as f:
        json.dump(summary, f, indent=2)

    logger.info("=" * 50)
    logger.info(f"Gold curation complete: {len(gold_df)} rows")
    logger.info(f"Assets: {len(summary['symbols'])}")
    logger.info("=" * 50)

    return 0


if __name__ == '__main__':
    exit(main())
