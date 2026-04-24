#!/usr/bin/env python3
"""
Silver Layer — Crypto Normalization
Reads from bronze/binance and produces normalized crypto time series

Output: silver/crypto/{symbol}_{interval}_normalized.parquet
"""

import os
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('crypto_silver')

BRONZE_DIR = Path('/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/bronze/binance')
SILVER_DIR = Path('/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/silver/crypto')


def load_bronze_data(date_str):
    """Load all bronze parquet files - check multiple date paths"""
    # Try current date first, then yesterday
    dates_to_try = [
        date_str,
        (datetime.strptime(date_str, '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
    ]
    
    for try_date in dates_to_try:
        bronze_path = BRONZE_DIR / try_date
        if bronze_path.exists():
            logger.info(f"Found bronze directory: {bronze_path}")
            break
    else:
        # Fallback: search all subdirectories
        logger.warning(f"No dated directory found, scanning all bronze subdirectories...")
        bronze_path = BRONZE_DIR


    
    all_data = []
    # Search recursively for parquet files
    parquet_files = list(bronze_path.rglob('*.parquet')) if bronze_path != BRONZE_DIR else list(BRONZE_DIR.rglob('*.parquet'))
    
    if bronze_path == BRONZE_DIR:
        # If searching root, limit depth to avoid picking up wrong files
        parquet_files = [f for f in parquet_files if f.parent.name.isdigit() or 'crypto' in f.name.lower()]
    
    for parquet_file in parquet_files:
        try:
            df = pd.read_parquet(parquet_file)
            all_data.append(df)
            logger.info(f"Loaded {parquet_file.name}: {len(df)} rows")
        except Exception as e:
            logger.error(f"Failed to load {parquet_file}: {e}")
    
    if not all_data:
        # Fallback: check for any parquet in bronze/binance directly
        for parquet_file in BRONZE_DIR.glob('*.parquet'):
            try:
                df = pd.read_parquet(parquet_file)
                all_data.append(df)
                logger.info(f"Loaded root level {parquet_file.name}: {len(df)} rows")
            except Exception as e:
                logger.error(f"Failed to load {parquet_file}: {e}")
    
    if not all_data:
        logger.warning(f"No data files found in {bronze_path}")
        return None
    
    combined = pd.concat(all_data, ignore_index=True)
    logger.info(f"Loaded {len(combined)} total rows from bronze")
    return combined


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


def save_silver(df, date_str):
    """Save normalized data to silver layer"""
    SILVER_DIR.mkdir(parents=True, exist_ok=True)
    
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


def main():
    """Main silver layer routine"""
    logger.info("=" * 50)
    logger.info("Crypto Silver Normalization Started")
    logger.info("=" * 50)
    
    # Use yesterday's date if running before market close
    date_str = (datetime.utcnow() - timedelta(days=0)).strftime('%Y%m%d')
    
    # Load bronze data
    bronze_df = load_bronze_data(date_str)
    if bronze_df is None:
        logger.error("No bronze data to process")
        return 1
    
    # Normalize
    normalized_df = normalize_crypto(bronze_df)
    
    # Save to silver
    save_silver(normalized_df, date_str)
    
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
