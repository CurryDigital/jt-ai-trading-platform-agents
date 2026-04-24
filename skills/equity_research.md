# Skill: Equity Research

## Alpha patterns for equity markets
- Momentum: 3-12 month price momentum, relative strength ranking
- Mean reversion: RSI < 30 buy / > 70 sell, Bollinger band touch
- Earnings: post-earnings announcement drift (PEAD), surprise magnitude
- Value: low P/E quintile vs high P/E quintile, book-to-market
- Quality: high ROE + low leverage + stable margins
- Size: small cap premium (historically but regime-dependent)
- Seasonal: January effect, sell-in-May, Santa rally, quarter-end
- IPO: day-2 buying (HK market), lockup expiry effects

## Data sources (gold layer)
- gold.stock_metrics_history: daily OHLCV + technical indicators
- gold.equity_kpis: fundamental metrics (P/E, ROE, margins)
- gold.earnings_signals: earnings dates, surprise, estimate vs actual
- gold.ipo_data: listing dates, offer prices, exchange

## Key considerations
- Trading hours vary: US 09:30-16:00 ET, HK 09:30-16:00 HKT
- Earnings seasons: Jan/Apr/Jul/Oct for US, Mar/Aug for HK
- Ex-dividend dates affect price — account for in backtests
