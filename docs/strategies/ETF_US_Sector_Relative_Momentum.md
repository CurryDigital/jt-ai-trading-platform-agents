<!-- source: authored -->
# US Sector Relative Momentum

| field | value |
|---|---|
| **strategy_id** | `ETF_US_Sector_Relative_Momentum` |
| **status** | paper |
| **tier / priority** | GOLDEN (per `gold.strategy_registry.priority`) |
| **asset class** | ETF (equity sector) |
| **execution mode** | PAPER |
| **signal mechanism** | computed(`agents/etl/gold/strategy/calc_etf_relative_momentum.py`) |
| **cadence** | daily (position-style, rebalances on regime/rank change) |
| **universe size** | 10 US sector/broad ETFs |

## Overview
Classic cross-sectional momentum: rank a basket of sector ETFs by their blended
trailing return and hold the top few, on the premise that recent relative
winners keep outperforming over the following weeks. A residual cash sleeve
caps concentration.

## Universe
The ETFs in `gold.strategy_registry.universe_tickers` for this strategy (SPY,
XLF, XLK, XLE, XLI, XLP, XLU, XLB, SMH, IWM per the current book). The universe
is read from the registry — NOT from the score table (fixed 2026-07-22; the old
code read its own output and went empty after any truncate).

## Buy-signal pipeline
**Inputs**: daily closes from `silver.unified_prices`.

**Composite momentum** per ETF = average of trailing total returns over four
**calendar-day** windows (fixed 2026-07-22 — previously trading-day counts were
used as calendar deltas, distorting every window):
- 1m = 30d, 3m = 91d, 6m = 182d, 12m = 365d
- each = `latest_close / close_on_or_before(today - Nd) - 1`

**Ranking**: sort ETFs by composite momentum (tie-break: most recent 1m return).

**Entry / weights**:
- top `TOP_N = 3` → `signal_action = BUY`, score `30.0` each
- the rest → `HOLD`, score `0`
- a synthetic `CASH` row gets score `10.0` (residual 10% cash)
Scores are emitted as target-weight percentages summing to 100, written to
`gold.strategy_ticker_scores`. The rebalancer
(`rebuild_paper_positions.py`) turns weights × assigned_capital ÷ price into
share targets and opens/closes paper positions accordingly.

## Exit logic
Position-style rebalance: a held ETF is closed when it drops out of the top-3
BUY set on a later run (handled by `rebuild_paper_positions.py`, which closes
positions no longer in the target set at the current price).

## Backtest summary (OOS)
From `gold.strategy_backtest_runs` (latest). As of 2026-07 the registry showed
Sharpe ≈ 1.43 / win rate ≈ 69% / max DD ≈ -7.7% over 34 OOS trades — but note
this strategy's ETF backtest rows were among those touched by the quarantined
`backfill_etf_win_rate_oos.py` reverse-sync; treat OOS win-rate as provisional
until qr_research re-delivers (OPERATOR_NOTES flag 6).

## Data dependencies
`silver.unified_prices` ← `bronze.yf_prices`; `gold.strategy_registry`
(universe + assigned_capital). Momentum needs ≥ 12 months of clean history per
ETF — the yfinance NULL-freeze bug (PIPELINE_DESIGN, 2026-07) would corrupt
older windows.

## Known issues / TODO
- Scores are fixed 30/30/30 regardless of the *strength* of momentum — a BUY
  conveys rank, not conviction. Consider weighting by composite spread.
- OOS win-rate provenance (see backtest summary).
