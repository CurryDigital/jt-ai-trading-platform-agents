#!/usr/bin/env python3
"""
FMP (Financial Modeling Prep) Bronze Ingestion
Pulls equity fundamentals, prices, and financial statements
Rate limited: 250 calls/day, 512 MB/month bandwidth

Output: bronze/fmp/{date}/{data_type}_{symbol}.parquet
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv('/home/ubuntu/.openclaw/.env')

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('fmp_bronze')

# FMP Configuration
FMP_API_KEY = os.getenv('FMP_API_KEY')
BASE_URL = 'https://financialmodelingprep.com/api/v3'

# Rate limiting: 250 calls/day = ~10 calls/hour on average
# We'll use a conservative limit and track usage
DAILY_CALL_LIMIT = 250
DAILY_BANDWIDTH_LIMIT_MB = 512

BRONZE_DIR = Path('/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/bronze/fmp')
STATE_DIR = Path('/home/ubuntu/.openclaw/workspace/quant_research/agents/etl/.state')

# Core tickers to track (can be expanded)
CORE_TICKERS = [
    'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'BRK-B',
    'JPM', 'V', 'JNJ', 'WMT', 'UNH', 'MA', 'PG', 'HD', 'CVX', 'MRK',
    'ABBV', 'PEP', 'KO', 'PFE', 'AVGO', 'COST', 'TMO', 'DIS', 'CSCO',
    'VZ', 'ADBE', 'WFC', 'ACN', 'ABT', 'CRM', 'CMCSA', 'TXN', 'NKE'
]


def load_api_state():
    """Load API usage state to respect daily limits"""
    state_file = STATE_DIR / 'fmp_api_state.json'
    today = datetime.utcnow().strftime('%Y-%m-%d')
    
    if state_file.exists():
        with open(state_file, 'r') as f:
            state = json.load(f)
        # Reset if new day
        if state.get('date') != today:
            state = {'date': today, 'calls_made': 0, 'bandwidth_mb': 0, 'endpoints_hit': []}
    else:
        state = {'date': today, 'calls_made': 0, 'bandwidth_mb': 0, 'endpoints_hit': []}
    
    return state


def save_api_state(state):
    """Save API usage state"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / 'fmp_api_state.json'
    with open(state_file, 'w') as f:
        json.dump(state, f, indent=2)


def check_rate_limit(state):
    """Check if we're within rate limits"""
    if state['calls_made'] >= DAILY_CALL_LIMIT:
        logger.error(f"Daily API limit reached: {state['calls_made']}/{DAILY_CALL_LIMIT}")
        return False
    if state['bandwidth_mb'] >= DAILY_BANDWIDTH_LIMIT_MB:
        logger.error(f"Daily bandwidth limit reached: {state['bandwidth_mb']:.2f}/{DAILY_BANDWIDTH_LIMIT_MB} MB")
        return False
    return True


def make_api_call(endpoint, params=None, track_bandwidth=True):
    """Make rate-limited API call to FMP"""
    state = load_api_state()
    
    if not check_rate_limit(state):
        return None
    
    url = f'{BASE_URL}/{endpoint}'
    call_params = {'apikey': FMP_API_KEY}
    if params:
        call_params.update(params)
    
    try:
        response = requests.get(url, params=call_params, timeout=30)
        response.raise_for_status()
        
        # Track usage
        state['calls_made'] += 1
        state['endpoints_hit'].append(endpoint)
        
        if track_bandwidth:
            # Estimate bandwidth (rough approximation)
            content_length = len(response.content) / (1024 * 1024)  # MB
            state['bandwidth_mb'] += content_length
        
        save_api_state(state)
        
        logger.info(f"API call {state['calls_made']}/{DAILY_CALL_LIMIT}: {endpoint}")
        
        # Be nice to the API - small delay between calls
        time.sleep(0.5)
        
        return response.json()
        
    except requests.exceptions.RequestException as e:
        logger.error(f"API call failed: {endpoint} - {e}")
        return None


def load_last_fetch_dates():
    """Load last fetch dates for incremental backfill"""
    state_file = STATE_DIR / 'fmp_last_fetch.json'
    if state_file.exists():
        with open(state_file, 'r') as f:
            return json.load(f)
    return {}


def save_last_fetch_dates(dates):
    """Save last fetch dates"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / 'fmp_last_fetch.json'
    with open(state_file, 'w') as f:
        json.dump(dates, f, indent=2)


def fetch_quote_short(tickers):
    """Fetch short quote (lightweight - for price data)"""
    symbols = ','.join(tickers)
    return make_api_call(f'quote-short/{symbols}')


def fetch_historical_price(ticker, from_date=None, to_date=None):
    """
    Fetch historical price data
    Uses incremental backfill - only fetches data since last fetch
    """
    last_fetch = load_last_fetch_dates()
    
    # If no from_date provided, use last fetch date or default to 5 years ago
    if not from_date:
        if ticker in last_fetch:
            from_date = last_fetch[ticker]
            logger.info(f"Incremental backfill for {ticker} from {from_date}")
        else:
            from_date = (datetime.utcnow() - timedelta(days=365*5)).strftime('%Y-%m-%d')
            logger.info(f"Full backfill for {ticker} from {from_date}")
    
    if not to_date:
        to_date = datetime.utcnow().strftime('%Y-%m-%d')
    
    data = make_api_call(f'historical-price-full/{ticker}', {
        'from': from_date,
        'to': to_date
    })
    
    if data and 'historical' in data:
        # Update last fetch date
        last_fetch[ticker] = to_date
        save_last_fetch_dates(last_fetch)
    
    return data


def fetch_fundamentals(ticker):
    """Fetch fundamentals (income statement, balance sheet, cash flow)"""
    # Only fetch quarterly to save API calls
    income = make_api_call(f'income-statement/{ticker}', {'period': 'quarter', 'limit': 20})
    balance = make_api_call(f'balance-sheet-statement/{ticker}', {'period': 'quarter', 'limit': 20})
    cashflow = make_api_call(f'cash-flow-statement/{ticker}', {'period': 'quarter', 'limit': 20})
    
    return {
        'income_statement': income,
        'balance_sheet': balance,
        'cash_flow': cashflow
    }


def process_historical_prices(data, ticker):
    """Convert historical price data to DataFrame"""
    if not data or 'historical' not in data:
        return None
    
    df = pd.DataFrame(data['historical'])
    df['ticker'] = ticker
    df['symbol'] = data.get('symbol', ticker)
    df['ingested_at'] = datetime.utcnow()
    df['source'] = 'fmp'
    
    # Ensure date column is datetime
    df['date'] = pd.to_datetime(df['date'])
    
    return df


def save_bronze(df, data_type, identifier, date_str):
    """Save data to bronze layer"""
    output_dir = BRONZE_DIR / date_str
    output_dir.mkdir(parents=True, exist_ok=True)
    
    filename = f"{data_type}_{identifier}.parquet"
    output_path = output_dir / filename
    
    df.to_parquet(output_path, index=False)
    logger.info(f"Saved {data_type} {identifier}: {len(df)} rows → {output_path}")
    return output_path


def main():
    """Main FMP ingestion routine"""
    logger.info("=" * 60)
    logger.info("FMP Bronze Ingestion Started")
    logger.info("=" * 60)
    
    if not FMP_API_KEY:
        logger.error("FMP_API_KEY not set")
        sys.exit(1)
    
    state = load_api_state()
    logger.info(f"API usage today: {state['calls_made']}/{DAILY_CALL_LIMIT} calls, "
                f"{state['bandwidth_mb']:.2f}/{DAILY_BANDWIDTH_LIMIT_MB} MB")
    
    if not check_rate_limit(state):
        logger.warning("Rate limit reached - skipping FMP ingestion")
        sys.exit(0)
    
    date_str = datetime.utcnow().strftime('%Y%m%d')
    results = {'success': [], 'failed': [], 'skipped': []}
    
    # Calculate remaining API budget
    remaining_calls = DAILY_CALL_LIMIT - state['calls_made']
    logger.info(f"Remaining API calls: {remaining_calls}")
    
    # Strategy: Prioritize based on remaining budget
    # - Always fetch quotes for all tickers (1 call for batch of up to ~35)
    # - Incremental price history for key tickers
    # - Fundamentals only if budget permits
    
    # 1. Fetch quotes for all tickers (batch in groups of 35 to stay safe)
    logger.info("Fetching quotes...")
    batch_size = 35
    for i in range(0, len(CORE_TICKERS), batch_size):
        batch = CORE_TICKERS[i:i+batch_size]
        quotes = fetch_quote_short(batch)
        if quotes:
            df = pd.DataFrame(quotes)
            df['ingested_at'] = datetime.utcnow()
            df['source'] = 'fmp'
            save_bronze(df, 'quotes', f'batch_{i//batch_size}', date_str)
            results['success'].append(f'quotes_batch_{i//batch_size}')
        else:
            results['failed'].append(f'quotes_batch_{i//batch_size}')
    
    # 2. Fetch historical prices for key tickers (incremental backfill)
    # Limit to top 10 most important to save API calls
    priority_tickers = CORE_TICKERS[:10]
    logger.info(f"Fetching historical prices for {len(priority_tickers)} priority tickers...")
    
    for ticker in priority_tickers:
        state = load_api_state()
        if not check_rate_limit(state):
            logger.warning("Rate limit reached - stopping price fetch")
            results['skipped'].extend(priority_tickers[priority_tickers.index(ticker):])
            break
        
        data = fetch_historical_price(ticker)
        if data:
            df = process_historical_prices(data, ticker)
            if df is not None and not df.empty:
                save_bronze(df, 'prices', ticker, date_str)
                results['success'].append(f'prices_{ticker}')
            else:
                results['failed'].append(f'prices_{ticker}')
        else:
            results['failed'].append(f'prices_{ticker}')
    
    # 3. Fetch fundamentals for top 5 tickers (if budget permits)
    state = load_api_state()
    remaining_calls = DAILY_CALL_LIMIT - state['calls_made']
    fundamentals_budget = 15  # 3 calls per ticker (income, balance, cashflow)
    
    if remaining_calls >= fundamentals_budget:
        fundamentals_tickers = CORE_TICKERS[:5]
        logger.info(f"Fetching fundamentals for {len(fundamentals_tickers)} tickers...")
        
        for ticker in fundamentals_tickers:
            state = load_api_state()
            if not check_rate_limit(state):
                logger.warning("Rate limit reached - stopping fundamentals fetch")
                results['skipped'].append(f'fundamentals_{ticker}')
                continue
            
            fundamentals = fetch_fundamentals(ticker)
            
            # Save each statement type
            for stmt_type, data in fundamentals.items():
                if data:
                    df = pd.DataFrame(data) if isinstance(data, list) else pd.DataFrame([data])
                    if not df.empty:
                        df['ticker'] = ticker
                        df['statement_type'] = stmt_type
                        df['ingested_at'] = datetime.utcnow()
                        df['source'] = 'fmp'
                        save_bronze(df, stmt_type, ticker, date_str)
            
            results['success'].append(f'fundamentals_{ticker}')
    else:
        logger.info(f"Skipping fundamentals - only {remaining_calls} calls remaining")
        results['skipped'].extend([f'fundamentals_{t}' for t in CORE_TICKERS[:5]])
    
    # Final summary
    state = load_api_state()
    logger.info("=" * 60)
    logger.info(f"FMP Ingestion Complete")
    logger.info(f"Success: {len(results['success'])}")
    logger.info(f"Failed: {len(results['failed'])}")
    logger.info(f"Skipped: {len(results['skipped'])}")
    logger.info(f"Total API calls: {state['calls_made']}/{DAILY_CALL_LIMIT}")
    logger.info(f"Bandwidth used: {state['bandwidth_mb']:.2f}/{DAILY_BANDWIDTH_LIMIT_MB} MB")
    logger.info("=" * 60)
    
    # Write summary
    summary_path = BRONZE_DIR / date_str / 'ingestion_summary.json'
    with open(summary_path, 'w') as f:
        json.dump({
            'date': date_str,
            'source': 'fmp',
            'api_calls': state['calls_made'],
            'bandwidth_mb': state['bandwidth_mb'],
            'success': results['success'],
            'failed': results['failed'],
            'skipped': results['skipped'],
            'timestamp': datetime.utcnow().isoformat()
        }, f, indent=2)
    
    # Exit code based on critical failures
    if len(results['failed']) > len(results['success']):
        sys.exit(1)
    sys.exit(0)


if __name__ == '__main__':
    main()
