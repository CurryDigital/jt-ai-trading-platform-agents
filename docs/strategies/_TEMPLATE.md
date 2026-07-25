<!-- source: authored | generated -->
# <Strategy display name>

| field | value |
|---|---|
| **strategy_id** | `<gold.strategy_registry.strategy_id>` |
| **status** | paper / live / paused / retired |
| **tier / priority** | EXPERIMENTAL / NEAR_GOLDEN / GOLDEN |
| **asset class** | equity / etf / crypto / fx / commodity |
| **execution mode** | SIMULATION / PAPER / LIVE |
| **signal mechanism** | criteria / computed(`<script>`) / ingested(`<file>`) |
| **cadence** | daily / weekly |
| **universe size** | N tickers |

## Overview
One paragraph: what edge this strategy is trying to capture and why it should
work (the economic/statistical rationale). No marketing — the honest thesis.

## Universe
The exact tickers traded, and how the universe is chosen (fixed list / screen /
sector map). Point at the source of truth (`gold.strategy_registry.universe_tickers`).

## Buy-signal pipeline  ← MANDATORY, be exact
The precise, reproducible path from raw data to a BUY. State every input, the
exact thresholds, and the table/column each value comes from. A reader must be
able to recompute today's signal by hand from this section. Examples of the
level of detail required:
- **Inputs**: `gold.kpis_metrics.macd_histogram`, `.volume_ratio`, prior-day macd.
- **Entry rule**: `macd_histogram >= 0.1 AND prev_macd_histogram <= -0.2 AND volume_ratio >= 1.2` (logic_mode=all).
- **Regime gate** (if any): only active when `gold.regime_label.regime = 'TREND'`.
- **Position sizing / weights**: how score → weight → shares.
- **Which script computes it**: file path + the function/SQL.
- **Where the result lands**: `gold.strategy_ticker_scores` / `gold.s9_*` / `consumption.*`.

## Exit logic
Take-profit / stop-loss / max-hold / rebalance-out rules, and the script that applies them.

## Backtest summary (OOS)
Sourced from `gold.strategy_backtest_runs` (the latest run). Sharpe, win rate,
max drawdown, trade count, profit factor, period. Note IS-vs-OOS and whether
any figure is estimated (should never be — see PIPELINE_DESIGN principle 1).

## Data dependencies
The upstream tables/sources this strategy needs fresh (so a staleness alert can
be traced to a dead signal). e.g. `gold.kpis_metrics` ← `silver.technical_indicators`
← `silver.unified_prices` ← `bronze.yf_prices`.

## Known issues / TODO
Anything not yet trustworthy about this strategy's numbers or wiring.
