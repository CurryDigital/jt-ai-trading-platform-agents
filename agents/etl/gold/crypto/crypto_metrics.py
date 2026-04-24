#!/usr/bin/env python3
"""
Gold Layer — Crypto Metrics Curation
Builds curated crypto metrics from silver layer for consumption

Output: gold/crypto/crypto_metrics_{date}.parquet
        Updates gold.stock_metrics_history via SQL
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('crypto_gold')

SILVER_DIR = Path('/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/silver/crypto')
GOLD_DIR = Path('/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/gold/crypto')


def load_silver_data(date_str):
    """Load silver normalized data"""
    silver_file = SILVER_DIR / f'crypto_combined_{date_str}.parquet'
    
    if not silver_file.exists():
        logger.error(f"Silver file not found: {silver_file}")
        return None
    
    df = pd.read_parquet(silver_file)
    logger.info(f"Loaded silver data: {len(df)} rows")
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
    
    # Focus on daily data for metrics calculation
    daily_df = df[df['interval'] == '1d'].copy()
    
    if daily_df.empty:
        logger.warning("No daily data found for metrics calculation")
        return None
    
    results = []
    
    for symbol, group in daily_df.groupby('symbol'):
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
        
        # Risk metrics (using available history)
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
        
        # Asset classification
        group['asset_type'] = 'crypto'
        group['asset_subtype'] = 'major' if symbol in ['BTCUSDT', 'ETHUSDT'] else 'altcoin'
        
        # Exchange info
        group['primary_exchange'] = 'binance'
        
        results.append(group)
    
    final_df = pd.concat(results, ignore_index=True)
    logger.info(f"Metrics calculated: {len(final_df)} rows")
    return final_df


def prepare_for_gold_schema(df):
    """
    Map to gold layer schema matching stock_metrics_history structure
    """
    logger.info("Mapping to gold schema...")
    
    # Rename columns to match gold schema
    column_mapping = {
        'timestamp': 'date',
        'symbol': 'ticker',
        'close': 'close_price',
        'open': 'open_price',
        'high': 'high_price',
        'low': 'low_price',
        'volume': 'volume',
        'returns': 'daily_return',
        'volatility_20': 'volatility_20d',
        'vwap': 'vwap',
        'rsi_14': 'rsi',
        'macd': 'macd',
        'macd_signal': 'macd_signal',
        'atr_14': 'atr_14d',
        'bb_upper': 'bollinger_upper',
        'bb_lower': 'bollinger_lower',
        'bb_middle': 'sma_20',
        'sharpe_30': 'sharpe_ratio',
        'max_drawdown': 'max_drawdown',
        'volume_ratio': 'volume_vs_avg'
    }
    
    gold_df = df.rename(columns=column_mapping)
    
    # Add required fields
    gold_df['sector'] = 'Cryptocurrency'
    gold_df['industry'] = 'Digital Assets'
    gold_df['currency'] = 'USD'
    gold_df['data_quality_score'] = 1.0  # Binance data is high quality
    gold_df['is_active'] = True
    gold_df['created_at'] = datetime.utcnow()
    gold_df['updated_at'] = datetime.utcnow()
    gold_df['source'] = 'binance'
    
    # Select final columns
    gold_columns = [
        'date', 'ticker', 'asset_type', 'asset_subtype', 'sector', 'industry',
        'open_price', 'high_price', 'low_price', 'close_price', 'volume',
        'daily_return', 'volatility_20d', 'vwap', 'rsi', 'macd', 'macd_signal',
        'atr_14d', 'bollinger_upper', 'bollinger_lower', 'sma_20',
        'sharpe_ratio', 'max_drawdown', 'volume_vs_avg', 'currency',
        'data_quality_score', 'is_active', 'primary_exchange', 'source',
        'created_at', 'updated_at'
    ]
    
    # Only include columns that exist
    available_cols = [c for c in gold_columns if c in gold_df.columns]
    gold_df = gold_df[available_cols]
    
    return gold_df


def save_gold(df, date_str):
    """Save gold layer data"""
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    
    # Save parquet
    output_path = GOLD_DIR / f'crypto_metrics_{date_str}.parquet'
    df.to_parquet(output_path, index=False)
    logger.info(f"Saved gold metrics: {len(df)} rows → {output_path}")
    
    # Generate SQL for inserting into stock_metrics_history
    sql_path = GOLD_DIR / f'insert_crypto_{date_str}.sql'
    generate_sql_inserts(df, sql_path)
    
    return output_path


def generate_sql_inserts(df, output_path):
    """Generate SQL insert statements for database loading"""
    logger.info(f"Generating SQL inserts → {output_path}")
    
    # This is a placeholder - actual implementation would use proper SQL generation
    # or use pandas to_sql with SQLAlchemy
    
    with open(output_path, 'w') as f:
        f.write("-- Crypto metrics insert statements\n")
        f.write(f"-- Generated: {datetime.utcnow().isoformat()}\n")
        f.write(f"-- Rows: {len(df)}\n\n")
        f.write("BEGIN;\n\n")
        
        # Generate INSERT statements
        for _, row in df.iterrows():
            cols = ', '.join(df.columns)
            vals = ', '.join([format_sql_value(v) for v in row.values])
            f.write(f"INSERT INTO stock_metrics_history ({cols}) VALUES ({vals});\n")
        
        f.write("\nCOMMIT;\n")
    
    logger.info(f"SQL file generated: {output_path}")


def format_sql_value(val):
    """Format a value for SQL insertion"""
    if pd.isna(val):
        return 'NULL'
    elif isinstance(val, str):
        # Escape single quotes by doubling them
        escaped = val.replace("'", "''")
        return f"'{escaped}'"
    elif isinstance(val, (datetime, pd.Timestamp)):
        return f"'{val.strftime('%Y-%m-%d %H:%M:%S')}'"
    elif isinstance(val, bool):
        return 'TRUE' if val else 'FALSE'
    else:
        return str(val)


def main():
    """Main gold layer routine"""
    logger.info("=" * 50)
    logger.info("Crypto Gold Curation Started")
    logger.info("=" * 50)
    
    date_str = datetime.utcnow().strftime('%Y%m%d')
    
    # Load silver data
    silver_df = load_silver_data(date_str)
    if silver_df is None:
        logger.error("No silver data to process")
        return 1
    
    # Calculate metrics
    metrics_df = calculate_metrics(silver_df)
    if metrics_df is None:
        logger.error("Failed to calculate metrics")
        return 1
    
    # Prepare for gold schema
    gold_df = prepare_for_gold_schema(metrics_df)
    
    # Save gold data
    save_gold(gold_df, date_str)
    
    # Summary
    summary = {
        'date': date_str,
        'source': 'binance',
        'silver_rows': len(silver_df),
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
