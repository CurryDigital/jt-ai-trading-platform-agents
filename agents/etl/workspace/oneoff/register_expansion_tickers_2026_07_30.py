#!/usr/bin/env python3
"""
One-off (kanban t_cf9c5c8b): register 26 universe-expansion ETF/HK tickers.

Writes:
  gold.asset_registry   (master; names from yfinance longName, fallback dict)
Then silver/sync_asset_registry.py propagates gold -> silver on its next run
(invoked separately to keep this step read-verify-write staged).

Conventions followed (from existing rows):
  asset_class: 'ETF' (US ETFs), 'ETF' (HK ETFs — e.g. 2800.HK-style rows use ETF/STOCK/HK Stock;
               we use 'ETF' for the two HK ETFs since get_active_tickers() filters on
               asset_class IN ('STOCK','ETF','INDEX'))
  market:      'US' / 'HK'
  is_active:   TRUE
"""
import sys, os
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

TICKERS = {
    # US — covered-call income
    'DIVO': ('ETF', 'US'), 'RYLD': ('ETF', 'US'),
    # US — small cap
    'IJR': ('ETF', 'US'), 'VB': ('ETF', 'US'), 'SCHA': ('ETF', 'US'), 'VTWO': ('ETF', 'US'),
    # US — HY/credit
    'SJNK': ('ETF', 'US'), 'USHY': ('ETF', 'US'), 'VCIT': ('ETF', 'US'), 'BKLN': ('ETF', 'US'),
    # US — dividend/defensive
    'SDY': ('ETF', 'US'), 'NOBL': ('ETF', 'US'), 'DVY': ('ETF', 'US'), 'USMV': ('ETF', 'US'), 'VIG': ('ETF', 'US'),
    # US — gold
    'IAU': ('ETF', 'US'), 'GLDM': ('ETF', 'US'), 'SGOL': ('ETF', 'US'),
    # HK/China
    '2828.HK': ('ETF', 'HK'), 'ASHR': ('ETF', 'US'), 'MCHI': ('ETF', 'US'),
    'FXI': ('ETF', 'US'), '3115.HK': ('ETF', 'HK'),
    # mid-cap + EUR proxy
    'IJH': ('ETF', 'US'), 'MDY': ('ETF', 'US'), 'FXE': ('ETF', 'US'),
}

FALLBACK_NAMES = {
    'DIVO': 'Amplify CWP Enhanced Dividend Income ETF',
    'RYLD': 'Global X Russell 2000 Covered Call ETF',
    'IJR': 'iShares Core S&P Small-Cap ETF',
    'VB': 'Vanguard Small-Cap ETF',
    'SCHA': 'Schwab U.S. Small-Cap ETF',
    'VTWO': 'Vanguard Russell 2000 ETF',
    'SJNK': 'SPDR Bloomberg Short Term High Yield Bond ETF',
    'USHY': 'iShares Broad USD High Yield Corporate Bond ETF',
    'VCIT': 'Vanguard Intermediate-Term Corporate Bond ETF',
    'BKLN': 'Invesco Senior Loan ETF',
    'SDY': 'SPDR S&P Dividend ETF',
    'NOBL': 'ProShares S&P 500 Dividend Aristocrats ETF',
    'DVY': 'iShares Select Dividend ETF',
    'USMV': 'iShares MSCI USA Min Vol Factor ETF',
    'VIG': 'Vanguard Dividend Appreciation ETF',
    'IAU': 'iShares Gold Trust',
    'GLDM': 'SPDR Gold MiniShares Trust',
    'SGOL': 'abrdn Physical Gold Shares ETF',
    '2828.HK': 'Hang Seng China Enterprises Index ETF',
    'ASHR': 'Xtrackers Harvest CSI 300 China A-Shares ETF',
    'MCHI': 'iShares MSCI China ETF',
    'FXI': 'iShares China Large-Cap ETF',
    '3115.HK': 'Global X Hang Seng High Dividend Yield ETF',
    'IJH': 'iShares Core S&P Mid-Cap ETF',
    'MDY': 'SPDR S&P MidCap 400 ETF Trust',
    'FXE': 'Invesco CurrencyShares Euro Trust',
}


def fetch_names(tickers):
    names = {}
    try:
        import yfinance as yf
    except ImportError:
        print("  yfinance unavailable — using fallback names")
        return {t: FALLBACK_NAMES[t] for t in tickers}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            nm = info.get('longName') or info.get('shortName')
            names[t] = nm or FALLBACK_NAMES[t]
            print(f"  {t}: {names[t]}")
        except Exception as e:
            names[t] = FALLBACK_NAMES[t]
            print(f"  {t}: info failed ({e}) — fallback: {names[t]}")
    return names


def main():
    names = fetch_names(list(TICKERS))
    conn = get_connection()
    cur = conn.cursor()
    n = 0
    for ticker, (asset_class, market) in TICKERS.items():
        cur.execute("""
            INSERT INTO gold.asset_registry
                (ticker, name, asset_class, market, is_active, created_at, updated_at)
            VALUES (%s, %s, %s, %s, TRUE, NOW(), NOW())
            ON CONFLICT (ticker) DO UPDATE SET
                name = EXCLUDED.name,
                asset_class = EXCLUDED.asset_class,
                market = EXCLUDED.market,
                is_active = TRUE,
                updated_at = NOW()
        """, (ticker, names[ticker], asset_class, market))
        n += 1
    conn.commit()
    conn.close()
    print(f"✅ gold.asset_registry — {n} tickers upserted")


if __name__ == '__main__':
    main()
