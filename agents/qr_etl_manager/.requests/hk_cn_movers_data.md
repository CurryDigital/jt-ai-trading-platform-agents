Subject: Missing HK and CN Stocks in Markets_Stocks_Overview

Description:
The `/api/market/movers` endpoint is only returning US stocks. The `consumption.Markets_Stocks_Overview` table appears to only contain US tickers.

Current State:
- API returns: 10 gainers + 10 losers (all US stocks like SNDK, CCL, WDC, AON)
- HK stocks: Only 1 loser found (0316.HK -0.1%)
- CN stocks: 0 found

Expected State:
- consumption.Markets_Stocks_Overview should include stocks from all markets:
  - US: AAPL, MSFT, etc.
  - HK: 0005.HK, 0388.HK, 2318.HK, etc.
  - CN: 000001, 000858, 600519, etc.

Root Cause:
The movers query only fetches from consumption.Markets_Stocks_Overview:
```sql
SELECT ticker, name, price, change_pct, volume, sector
FROM consumption.Markets_Stocks_Overview
WHERE change_pct IS NOT NULL AND change_pct != 0 AND price > 0
ORDER BY change_pct DESC
```

This view needs to include HKEX and CN market stocks with their change percentages.

Data Sources Needed:
- HKEX stocks: bronze/silver layer for HK tickers (.HK suffix)
- CN stocks: Shanghai/Shenzhen exchange tickers

Requester: qr_frontend
Date: 2026-04-17
Impact: Markets tab showing "No CN data" and minimal HK data