Subject: Request for New Consumption Views - Market Sentiment & Breadth

Description:
The Markets Overview tab in the trading platform is displaying incorrect/placeholder values for key market indicators. Investigation shows the required consumption views do not exist.

Missing Consumption Views:

1. consumption.Market_Sentiment
   Required columns:
   - fear_greed_index (INT 0-100): Composite sentiment indicator
   - fear_greed_label (TEXT): 'Extreme Fear' | 'Fear' | 'Neutral' | 'Greed' | 'Extreme Greed'
   - vix (FLOAT): Current VIX value
   - put_call_ratio (FLOAT): Current put/call ratio
   - updated_at (TIMESTAMP)

   Data sources:
   - Fear & Greed: CNN Money API or composite calculation from VIX, market momentum, breadth
   - VIX: ^VIX ticker from yfinance (already in silver.unified_prices)
   - Put/Call: CBOE or similar market data API

2. consumption.Market_Breadth
   Required columns:
   - advancing (INT): Number of advancing stocks
   - declining (INT): Number of declining stocks  
   - unchanged (INT): Number of unchanged stocks
   - new_52w_highs (INT): Count of stocks at 52-week highs
   - new_52w_lows (INT): Count of stocks at 52-week lows
   - pct_above_50ma (FLOAT): % of stocks above 50-day MA
   - pct_above_200ma (FLOAT): % of stocks above 200-day MA
   - updated_at (TIMESTAMP)

   Data sources:
   - Adv/Decl/Unchanged: Count from consumption.Markets_Stocks_Overview
   - 52W highs/lows: Compare current close to MAX/MIN over 252 trading days
   - MA percentages: Calculate from silver.unified_prices with 50/200 day windows

Priority: HIGH
Impact: Frontend Markets tab showing hardcoded zeros to users

Current Workaround: None - data must come from consumption layer per architecture

Requester: qr_frontend
Date: 2026-04-16