# Skill: Strategy Registry

A living catalog of strategy types the system can backtest. Grows as
the Researcher discovers new patterns and the Architect validates them.

## Equity Strategies

| Type | Signal | Entry | Exit | Data tables |
|------|--------|-------|------|-------------|
| momentum | MA crossover, relative strength | Price crosses above MA | Crosses below MA or time stop | stock_metrics_history |
| mean_reversion | RSI extreme, z-score | Oversold (z < -2) | Mean reversion (z > 0) | stock_metrics_history |
| breakout | Channel breakout | New high + volume confirm | Trailing stop or channel re-entry | stock_metrics_history |
| pairs | Spread z-score | z > +2 or z < -2 | z returns to 0 | stock_metrics_history (2 assets) |
| earnings_drift | Earnings surprise | Day after surprise | 5-day or 10-day hold | earnings_signals + stock_metrics_history |
| ipo_timing | IPO listing date | Day N post-listing | Fixed hold (e.g. 3-5 days) | ipo_data + stock_metrics_history |
| index_rebalance | Index add/delete announcement | Buy additions, short deletions | Effective date + 2 days | stock_metrics_history |
| seasonal | Calendar date | Start of seasonal window | End of seasonal window | stock_metrics_history |
| factor_value | P/E, P/B quintiles | Long bottom quintile | Monthly rebalance | equity_kpis + stock_metrics_history |

## Crypto Strategies

| Type | Signal | Entry | Exit | Data tables |
|------|--------|-------|------|-------------|
| btc_momentum | BTC trend | BTC crosses above 20d MA | Crosses below | crypto_metrics |
| alt_rotation | BTC dominance shift | BTC.D drops below threshold | BTC.D rises back | crypto_metrics |
| cross_crypto | Correlation break | BTC/ETH ratio extreme | Ratio mean reversion | crypto_metrics |

## FX Strategies

| Type | Signal | Entry | Exit | Data tables |
|------|--------|-------|------|-------------|
| carry_trade | Yield differential | Long high-yield ccy | Monthly rebalance | fx_metrics |
| session_momentum | Session open/close | Momentum into London/NY | Session close | fx_metrics |

## Commodity Strategies

| Type | Signal | Entry | Exit | Data tables |
|------|--------|-------|------|-------------|
| oil_momentum | Oil trend | Crosses above MA | Trailing stop | commodity_metrics |
| gold_safe_haven | VIX spike | Buy gold when VIX > 30 | VIX normalises | commodity_metrics + market_metrics |
| commodity_spread | Inter-commodity ratio | Gold/silver ratio extreme | Ratio reversion | commodity_metrics |

## Cross-Asset / Macro Strategies

| Type | Signal | Entry | Exit | Data tables |
|------|--------|-------|------|-------------|
| cross_asset_signal | One asset triggers another | Conditional (e.g. BTC drops → buy oil) | Time stop or target | Multiple gold tables |
| regime_switch | VIX/vol regime change | Rotate allocation by regime | Regime reverts | market_metrics + stock_metrics_history |
| geopolitical_event | News event (tariff, war, policy) | Trade affected sector | Fixed hold 3-5 days | stock_metrics_history |
| rate_sensitivity | Fed rate change | Long/short rate-sensitive | Hold through cycle | stock_metrics_history + market_metrics |

## Adding new strategy types

When an experiment passes QA with strategy_type='custom' 3+ times:
1. The Architect adds it to this registry with its signal/entry/exit pattern
2. The Researcher uses it in future idea generation
3. The backtest engine references it for formula templates
