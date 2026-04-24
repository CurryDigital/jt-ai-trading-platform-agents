# Skill: Debate Framework

Structured adversarial analysis for trading strategies.
Inspired by TradingAgents (AAAI 2025) Bull/Bear debate pattern.

## Debate structure

### Round 1 — Bull Case
Argue FOR the strategy. Find the strongest reasons it should work:
- Historical analogues where similar signals produced alpha
- Current macro regime supporting the thesis
- Statistical strength of the backtest (Sharpe, drawdown, trade count)
- Edge that may not be fully captured by the numbers
- Margin of safety in the risk evaluation

### Round 2 — Bear Case
Argue AGAINST the strategy. Probe every weakness:
- Overfitting risk: IS/OOS Sharpe divergence, curve-fitting signals
- Regime dependence: would this fail in opposite regime?
- Crowding risk: is this a well-known, over-exploited pattern?
- Data quality: thin volume, survivorship bias, backfill
- Tail risk: black swan scenarios, correlated drawdowns
- Alpha decay: how quickly would this edge erode if traded?

### Conviction score (0.0 — 1.0)

| Score | Interpretation | Action |
|-------|---------------|--------|
| 0.8-1.0 | Strong — bull case clearly dominates | Proceed to QA |
| 0.5-0.7 | Moderate — both sides have merit | Proceed with caution |
| 0.3-0.5 | Mixed — bear case has strong points | QA will likely scrutinise |
| 0.0-0.3 | Weak — bear case dominates | Likely rejected |

### Calibration
- Track: did high-conviction strategies actually pass QA?
- Track: did low-conviction strategies fail?
- If miscalibrated: adjust weighting of bull/bear arguments
