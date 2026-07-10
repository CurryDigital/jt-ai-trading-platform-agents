import os, sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection
conn = get_connection()
cur = conn.cursor()

target = ['SPY','VTI','VOO','VUG','VYM','SCHD','JEPI','JEPQ','DIA','IWB','IWV',
'QQQ','IWF','VGT','XLK','SMH','SOXX','IGV','SKYY','CIBR','HACK','QCLN','ARKK','ARKQ','FNGU','TQQQ','QLD','SSO',
'BND','AGG','TLT','IEF','LQD','HYG','JNK','EMB','MUB','VTEB','GOVT',
'GLD','SLV','USO','UNG','DBA','DBC','CPER','WEAT','PALL','PPLT',
'VNQ','SCHH','XLRE','IYR','REM',
'BITO','IBIT','FBTC']

cur.execute("""
    SELECT ticker, asset_class, market, sector, is_active
    FROM gold.asset_registry
    WHERE asset_class IN ('ETF','INDEX')
    ORDER BY ticker;
""")
print('=== Existing ETFs/INDEX in asset_registry ===')
for r in cur.fetchall(): print(r)

cur.execute("""
    SELECT a.ticker, COUNT(k.*) as kpis_rows, COUNT(s.*) as smh_rows
    FROM gold.asset_registry a
    LEFT JOIN gold.kpis_metrics k ON k.ticker=a.ticker
    LEFT JOIN gold.stock_metrics_history s ON s.ticker=a.ticker
    WHERE a.asset_class IN ('ETF','INDEX')
    GROUP BY a.ticker
    ORDER BY a.ticker;
""")
print('\n=== Existing ETF coverage ===')
for r in cur.fetchall(): print(r)

cur.execute("""
    SELECT ticker, COUNT(*) as rows, MIN(date) as first, MAX(date) as last
    FROM bronze.yf_prices
    WHERE ticker = ANY(%s)
    GROUP BY ticker
    ORDER BY rows DESC, ticker;
""", (target,))
print('\n=== Bronze yf_prices coverage for target 50 ETFs ===')
for r in cur.fetchall(): print(r)

conn.close()
