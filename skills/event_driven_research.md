# Skill: Event-Driven Research

## Strategy patterns based on events
- IPO timing: buy day N after listing, fixed hold period
- Earnings plays: buy/sell around earnings announcement
- Index rebalancing: buy additions, short deletions
- M&A arbitrage: spread convergence after announcement
- Dividend capture: buy before ex-date, sell after
- Calendar effects: month-end rebalancing flows, year-end tax-loss selling

## Key characteristic: DYNAMIC asset universe
Unlike momentum or mean reversion where you pick assets upfront,
event-driven strategies select assets BY the event:
- "All HK IPOs listed this quarter"
- "All S&P 500 additions announced this month"
- "All stocks with earnings surprise > 10% this week"

The backtest code must handle dynamic universe construction.

## Data sources
- gold.ipo_data: listing dates, exchange, sector
- gold.earnings_signals: surprise, dates, estimates
- gold.market_metrics: index changes, rebalancing events
- gold.stock_metrics_history: price data for backtesting
