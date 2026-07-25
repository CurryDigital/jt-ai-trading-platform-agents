<!-- source: authored -->
# S9 MACD Momentum V2

| field | value |
|---|---|
| **strategy_id** | `S9_MACD_Momentum_V2` |
| **status** | paper |
| **tier / priority** | (per `gold.strategy_registry.priority`) |
| **asset class** | equity |
| **execution mode** | PAPER/SIMULATION |
| **signal mechanism** | computed(`agents/signals/pipeline/s9_macd_daily.py`) + criteria(`gold.strategy_signal_criteria`) |
| **cadence** | daily |
| **universe size** | 35 US large-cap growth/quality names |

## Overview
A MACD-histogram momentum-reversal strategy: it buys a name the day its MACD
histogram flips decisively from negative to positive on above-average volume,
betting that a fresh momentum turn in a trending market continues for a few
days. Only active in a TREND regime, holds one position at a time.

## Universe
Fixed 35-ticker list (AAPL, ABBV, ACN, ADBE, AMAT, AMD, AMZN, BA, COST, CRM,
DHR, DOCU, GOOGL, HD, INTU, LIN, LLY, MA, META, MSFT, NFLX, NKE, NVDA, PYPL,
QCOM, ROKU, SHOP, SNOW, TMO, TMUS, TSLA, TXN, UNH, V, ZM) — see the `UNIVERSE`
constant in `s9_macd_daily.py` and `gold.strategy_registry.universe_tickers`.

## Buy-signal pipeline
**Inputs** (all from `gold.kpis_metrics`, the EMA-based indicators computed once
in `silver/compute_technical_indicators.py`):
- `macd_histogram` (today)
- `macd_histogram` lagged one trading day → `prev_macd_hist`
- `volume_ratio`

**Regime gate**: only runs when today's `gold.regime_label.regime = 'TREND'`.

**Single-position constraint**: skips generation if an OPEN `gold.s9_paper_trades`
row already exists for the strategy.

**Entry rule** (all three must hold — logic_mode `all`):
```
macd_histogram      >= 0.1
prev_macd_histogram <= -0.2
volume_ratio        >= 1.2
```
Among all tickers passing, the first alphabetically is taken (backtest tie-break).

**Two consistent paths compute this** (both now read the same EMA-based
`macd_histogram`, so they agree):
1. `s9_macd_daily.py::find_signals` — the dedicated runner; writes
   `gold.s9_macd_signals` + opens a paper trade in `gold.s9_paper_trades`.
2. `build_strategy_scores.py` — evaluates the same thresholds from
   `gold.strategy_signal_criteria` into `gold.strategy_ticker_scores` (score =
   % of criteria met; BUY only when all met).

**Sizing**: single position; `size_position()` uses a 1% vol target (paper).

## Exit logic
`s9_macd_daily.py::check_exits`, evaluated daily on the OPEN trade:
- take-profit at `+3%` (`TP_PCT`)
- stop-loss at `-2%` (`SL_PCT`)
- max hold `5` trading days (`MAX_HOLD_DAYS`)

## Backtest summary (OOS)
From `gold.strategy_backtest_runs` (latest run). As of the 2026-07-17 sync:
Sharpe ≈ 9.18 over 53 OOS trades, win rate ≈ 68% — the strongest
statistically-backed strategy in the book. Confirm live via the registry.

## Data dependencies
`gold.regime_label` ← regime pipeline; `gold.kpis_metrics.macd_histogram/
volume_ratio` ← `silver.technical_indicators` ← `silver.unified_prices` ←
`bronze.yf_prices`. If `macd_histogram` is NULL (the 2026-07 indicator bug),
this strategy silently never fires — see PIPELINE_DESIGN S1.

## Known issues / TODO
- The `s9_macd_daily.py` runner and the `build_strategy_scores` criteria path
  are two writers for one strategy; they now use the same MACD definition but
  should eventually be one path.
