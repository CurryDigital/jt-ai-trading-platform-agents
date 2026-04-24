#!/usr/bin/env python3
"""
Bronze Ingestion: FRED (Federal Reserve Economic Data)
Tables: bronze.fred_macro_indicators
Source: FRED API (api.stlouisfed.org)

Key Indicators:
  DFF  - Federal Funds Effective Rate
  CPIAUCSL - Consumer Price Index (All Urban Consumers)
  UNRATE - Unemployment Rate
  GDP - Gross Domestic Product (quarterly)
  T10Y2Y - 10-Year minus 2-Year Treasury Yield Spread
  DGS10 - 10-Year Treasury Constant Maturity Rate
  DGS2  - 2-Year Treasury Constant Maturity Rate
"""
import sys, os, requests
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date, timedelta

# FRED API key from environment
FRED_API_KEY = os.environ.get('FRED_API_KEY')

FRED_SERIES = {
    'DFF': ('Federal Funds Effective Rate', 'pct', 'daily'),
    'CPIAUCSL': ('Consumer Price Index', 'index', 'monthly'),
    'CPILFESL': ('Core CPI (Less Food & Energy)', 'index', 'monthly'),
    'UNRATE': ('Unemployment Rate', 'pct', 'monthly'),
    'PAYEMS': ('Total Nonfarm Payrolls', 'thousands', 'monthly'),
    'GDP': ('Gross Domestic Product', 'billions_usd', 'quarterly'),
    'T10Y2Y': ('10Y-2Y Treasury Spread', 'pct', 'daily'),
    'DGS10': ('10-Year Treasury Rate', 'pct', 'daily'),
    'DGS2': ('2-Year Treasury Rate', 'pct', 'daily'),
    'DTB3': ('3-Month Treasury Bill Rate', 'pct', 'daily'),
    'BAMLH0A0HYM2': ('High Yield Spread', 'bps', 'daily'),
    'VIXCLS': ('VIX Volatility Index', 'index', 'daily'),
    'DEXUSEU': ('USD/EUR Exchange Rate', 'rate', 'daily'),
    'DEXCHUS': ('USD/CNY Exchange Rate', 'rate', 'daily'),
}

def fetch_fred_data(series_id, start_date='2024-01-01'):
    """Fetch data from FRED API"""
    if not FRED_API_KEY:
        print(f"⚠️  FRED_API_KEY not set - cannot fetch {series_id}")
        return []
    
    url = 'https://api.stlouisfed.org/fred/series/observations'
    params = {
        'series_id': series_id,
        'api_key': FRED_API_KEY,
        'file_type': 'json',
        'observation_start': start_date,
        'sort_order': 'asc',
    }
    
    try:
        resp = requests.get(url, params=params, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        return data.get('observations', [])
    except Exception as e:
        print(f"  Error fetching {series_id}: {e}")
        return []

def ingest_fred_data():
    conn = get_connection()
    cur = conn.cursor()
    total_inserted = 0
    
    # Calculate start date (fetch last 6 months to be safe)
    start_date = (date.today() - timedelta(days=180)).isoformat()
    
    for series_id, (name, units, freq) in FRED_SERIES.items():
        print(f"→ {series_id}: {name}")
        observations = fetch_fred_data(series_id, start_date)
        
        inserted = 0
        for obs in observations:
            val = obs.get('value', '')
            obs_date = obs.get('date')
            
            # Skip missing values (FRED uses '.' for missing)
            if not val or val == '.' or val == '':
                continue
            
            try:
                cur.execute("""
                    INSERT INTO bronze.fred_macro_indicators
                        (series_id, indicator_name, units, frequency, 
                         date, value, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (series_id, date) DO UPDATE SET
                        value = EXCLUDED.value,
                        created_at = NOW()
                """, (series_id, name, units, freq, obs_date, float(val)))
                inserted += 1
            except Exception as e:
                print(f"    Row error {series_id} {obs_date}: {e}")
        
        print(f"   {inserted} rows upserted")
        total_inserted += inserted
    
    conn.commit()
    conn.close()
    print(f"\n✅ bronze.fred_macro_indicators — {total_inserted} rows upserted")

def copy_to_gold():
    """Copy bronze data to gold.macro_indicators"""
    conn = get_connection()
    cur = conn.cursor()
    
    cur.execute("""
        INSERT INTO gold.macro_indicators
            (date, indicator_name, value, created_at)
        SELECT 
            date,
            series_id || ' - ' || indicator_name,
            value,
            NOW()
        FROM bronze.fred_macro_indicators
        WHERE date >= '2024-01-01'
        ON CONFLICT (indicator_name, date) DO UPDATE SET
            value = EXCLUDED.value,
            created_at = NOW();
    """)
    
    upserted = cur.rowcount
    conn.commit()
    conn.close()
    print(f"✅ gold.macro_indicators — {upserted} rows upserted")

if __name__ == "__main__":
    ingest_fred_data()
    copy_to_gold()
