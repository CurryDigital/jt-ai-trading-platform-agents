#!/usr/bin/env python3
"""
Binance Crypto Bronze Ingestion
Pulls OHLCV data for major trading pairs from Binance API

Output: bronze/binance/{date}/{symbol}_{interval}.parquet
"""

import os
import sys
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv('/home/ubuntu/.openclaw/.env')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('binance_bronze')

# Configuration
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_SECRET = os.getenv('BINANCE_SECRET')
BASE_URL = 'https://api.binance.com'

# Major crypto pairs to track
CRYPTO_PAIRS = [
    'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT',
    'ADAUSDT', 'AVAXUSDT', 'DOTUSDT', 'MATICUSDT', 'LINKUSDT',
    'UNIUSDT', 'LTCUSDT', 'ATOMUSDT', 'ETCUSDT', 'XLMUSDT'
]

INTERVALS = ['1d', '4h', '1h']  # Daily, 4-hour, 1-hour candles

BRONZE_DIR = Path('/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/bronze/binance')


def check_credentials():
    """Verify Binance credentials are set and valid"""
    if not BINANCE_API_KEY or BINANCE_API_KEY == 'your_binance_api_key':
        logger.error("BINANCE_API_KEY not configured in .env")
        return False
    if not BINANCE_SECRET or BINANCE_SECRET == 'your_binance_secret':
        logger.error("BINANCE_SECRET not configured in .env")
        return False
    return True


def get_klines(symbol, interval, limit=1000, start_time=None, end_time=None):
    """Fetch candlestick data from Binance"""
    endpoint = f'{BASE_URL}/api/v3/klines'
    
    params = {
        'symbol': symbol,
        'interval': interval,
        'limit': limit
    }
    
    if start_time:
        params['startTime'] = int(start_time.timestamp() * 1000)
    if end_time:
        params['endTime'] = int(end_time.timestamp() * 1000)
    
    headers = {'X-MBX-APIKEY': BINANCE_API_KEY}
    
    try:
        response = requests.get(endpoint, params=params, headers=headers, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch {symbol} {interval}: {e}")
        return None


def process_klines(data, symbol, interval):
    """Convert Binance klines to DataFrame"""
    if not data:
        return None
    
    # Binance kline format:
    # [open_time, open, high, low, close, volume, close_time, quote_volume, 
    #  trades, taker_buy_base, taker_buy_quote, ignore]
    df = pd.DataFrame(data, columns=[
        'open_time', 'open', 'high', 'low', 'close', 'volume',
        'close_time', 'quote_volume', 'trades', 'taker_buy_base',
        'taker_buy_quote', 'ignore'
    ])
    
    # Convert types
    numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume', 
                    'taker_buy_base', 'taker_buy_quote']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df['trades'] = pd.to_numeric(df['trades'], errors='coerce').astype(int)
    
    # Convert timestamps
    df['timestamp'] = pd.to_datetime(df['open_time'], unit='ms')
    df['close_timestamp'] = pd.to_datetime(df['close_time'], unit='ms')
    
    # Add metadata
    df['symbol'] = symbol
    df['interval'] = interval
    df['source'] = 'binance'
    df['ingested_at'] = datetime.utcnow()
    
    return df


def save_bronze(df, symbol, interval, date_str):
    """Save DataFrame to bronze layer"""
    output_dir = BRONZE_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{symbol}_{interval}.parquet"
    output_path = output_dir / filename
    
    df.to_parquet(output_path, index=False)
    logger.info(f"Saved {symbol} {interval}: {len(df)} rows → {output_path}")
    return output_path


def main():
    """Main ingestion routine"""
    logger.info("=" * 50)
    logger.info("Binance Bronze Ingestion Started")
    logger.info("=" * 50)
    
    # Check credentials
    if not check_credentials():
        logger.error("Invalid or missing Binance credentials")
        sys.exit(1)
    
    date_str = datetime.utcnow().strftime('%Y%m%d')
    results = {'success': [], 'failed': []}
    
    # Fetch data for each pair and interval
    for symbol in CRYPTO_PAIRS:
        for interval in INTERVALS:
            logger.info(f"Fetching {symbol} {interval}...")
            
            # Get last 1000 candles (max allowed)
            data = get_klines(symbol, interval, limit=1000)
            
            if data is None:
                results['failed'].append(f"{symbol}_{interval}")
                continue
            
            df = process_klines(data, symbol, interval)
            
            if df is None or df.empty:
                results['failed'].append(f"{symbol}_{interval}")
                continue
            
            save_bronze(df, symbol, interval, date_str)
            results['success'].append(f"{symbol}_{interval}")
    
    # Summary
    logger.info("=" * 50)
    logger.info(f"Success: {len(results['success'])} pairs")
    logger.info(f"Failed: {len(results['failed'])} pairs")
    if results['failed']:
        logger.warning(f"Failed pairs: {results['failed']}")
    logger.info("=" * 50)
    
    # Write summary for downstream use
    summary_path = BRONZE_DIR / date_str / 'ingestion_summary.json'
    with open(summary_path, 'w') as f:
        json.dump({
            'date': date_str,
            'source': 'binance',
            'asset_type': 'crypto',
            'success_count': len(results['success']),
            'failed_count': len(results['failed']),
            'success': results['success'],
            'failed': results['failed'],
            'timestamp': datetime.utcnow().isoformat()
        }, f, indent=2)
    
    # Exit code based on success rate
    if len(results['failed']) > len(results['success']):
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
