# Skill: Backtest Engine

## Purpose
Defines the exact metrics the Algo agent must compute for every
backtest, how to split IS/OOS periods, and what constitutes a
valid result. The Risk and QA agents depend on these metric
definitions being consistent — never deviate from this contract.

Load this skill: Algo agent only.

---

## IS / OOS Split

Always split the date_range into two equal halves:
- In-Sample (IS): first 50% of trading days
- Out-of-Sample (OOS): remaining 50%

```python
midpoint = start + (end - start) / 2
is_range  = (start, midpoint)
oos_range = (midpoint + 1day, end)
```

Never train or optimise on OOS data. OOS is sacred — it is the
only honest measure of live performance.

---

## Required metrics (all must be present in backtest.completed payload)

| Metric | Description | Type |
|--------|-------------|------|
| `sharpe_is` | Sharpe ratio over IS period | float |
| `sharpe_oos` | Sharpe ratio over OOS period | float |
| `sharpe_ratio_is_oos` | sharpe_oos / sharpe_is — overfitting signal | float |
| `returns_annualised_is` | Annualised return % over IS | float |
| `returns_annualised_oos` | Annualised return % over OOS | float |
| `max_drawdown` | Maximum peak-to-trough drawdown (negative float, e.g. -0.18) | float |
| `win_rate` | Fraction of trades that were profitable (0.0–1.0) | float |
| `trade_count_is` | Number of completed trades in IS period | int |
| `trade_count_oos` | Number of completed trades in OOS period | int |
| `avg_holding_days` | Average trade duration in calendar days | float |
| `turnover_rate` | Annualised portfolio turnover (1.0 = 100%) | float |

Never omit a metric. If a metric cannot be computed (e.g. zero trades),
set it to 0.0 and log a warning — do not omit the key.

---

## Sharpe ratio formula

```
sharpe = (mean_daily_return - risk_free_rate) / std_daily_return × sqrt(252)
risk_free_rate = 0.0  (conservative — do not assume positive risk-free return)
```

Use daily returns. Do not use weekly or monthly returns.

---

## Strategy implementations

### momentum
```
signal = price / rolling_mean(lookback_window) - 1
entry:  signal crosses above +entry_threshold standard deviations
exit:   signal crosses below -exit_threshold standard deviations
        OR position age exceeds lookback_window × 2 days
```

### mean_reversion
```
signal = (price - rolling_mean(lookback_window)) / rolling_std(lookback_window)
entry:  signal < -entry_threshold  (buy oversold)
exit:   signal > +exit_threshold   (sell overbought)
```

### breakout
```
signal = price / rolling_max(lookback_window)
entry:  price breaks above rolling_max × (1 + entry_threshold / 100)
exit:   price drops below rolling_min × (1 - exit_threshold / 100)
```

### pairs
```
Requires exactly 2 tickers in asset_universe.
spread = log(price_A / price_B)
z_score = (spread - rolling_mean(spread, lookback_window)) / rolling_std(spread, lookback_window)
entry:  z_score > +entry_threshold (short spread) or < -entry_threshold (long spread)
exit:   |z_score| < exit_threshold
```

---

## Position sizing

Equal-weight across all positions. No leverage.
Max positions open simultaneously: len(asset_universe) / 2 (rounded up).
Transaction costs: 0.1% per trade (each side). Always include.

---

## Timeout

If backtest takes longer than 25 minutes, raise RetryableError.
The event stays pending and Monitor will requeue if needed.

---

## What NOT to do

- Never optimise parameters to maximise IS Sharpe — that is the Exp. Manager's job
- Never look at OOS data while computing IS signals
- Never report only IS metrics — both periods are mandatory
- Never editorialize: "poor results, unlikely to pass" — report numbers, exit
