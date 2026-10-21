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

**Entry / weights** (tuned 2026-09-18, kanban t_3741eba6, backtest run_number=4):
- top `TOP_N = 4` → `signal_action = BUY`, score `22.5` each
- the rest → `HOLD`, score `0`
- a synthetic `CASH` row gets score `10.0` (residual 10% cash)
Scores are emitted as target-weight percentages summing to 100, written to
`gold.strategy_ticker_scores`. The scheduled writer is
`agents/signals/pipeline/build_rotation_signals.py` (config `top_n=4`,
`cash_residual=0.10` → fractional weights 0.225/0.10); this engine stays in
sync with it. The rebalancer
(`rebuild_paper_positions.py`) turns weights × assigned_capital ÷ price into
share targets and opens/closes paper positions accordingly.

## Exit logic
Position-style rebalance: a held ETF is closed when it drops out of the top-4
BUY set on a later run (handled by `rebuild_paper_positions.py`, which closes
positions no longer in the target set at the current price).

## Backtest summary (OOS)
From `gold.strategy_backtest_runs` run_number=4 (tuned, KEEP-TUNED 2026-09-18
review): Sharpe 1.611 / return 38.2% / max DD -6.8% over 38 OOS trades,
holdout 2026-07-01..2026-09-17 +1.15% Sharpe 0.45 PASS. Earlier runs showed
Sharpe ≈ 1.43 / win rate ≈ 69% — but note this strategy's ETF backtest rows
were among those touched by the quarantined `backfill_etf_win_rate_oos.py`
reverse-sync; treat pre-run-4 OOS win-rate as provisional (OPERATOR_NOTES
flag 6).

## Data dependencies
`silver.unified_prices` ← `bronze.yf_prices`; `gold.strategy_registry`
(universe + assigned_capital). Momentum needs ≥ 12 months of clean history per
ETF — the yfinance NULL-freeze bug (PIPELINE_DESIGN, 2026-07) would corrupt
older windows.

## Known issues / TODO
- Scores are fixed 30/30/30 regardless of the *strength* of momentum — a BUY
  conveys rank, not conviction. Consider weighting by composite spread.
- OOS win-rate provenance (see backtest summary).
