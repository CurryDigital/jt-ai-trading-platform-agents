# pipeline/ — signal-generation stage

Scripts that COMPUTE or INGEST trading signals. Moved here from
`agents/etl/` on 2026-07-10: the ETL agent's job ends at building
gold-layer data; deciding what to trade from that data is the signal
agent's job. Everything here runs via `../run_signal_cycle.sh`, which
gates on `gold_layer_state` so signals are never computed from a broken
gold layer.

| Script | Role |
|---|---|
| `build_strategy_scores.py` | Evaluates `gold.strategy_signal_criteria` against latest KPIs per registry universe → `gold.strategy_ticker_scores` |
| `s9_macd_daily.py` | S9 MACD momentum daily signal generation |
| `ingest_paper_signal.py` | Parameterized ingester for research-approved paper-strategy signal files (`--all` or `--strategy-id/--strategy-name`) |
| `ingest_etf_multi_asset_live_signal.py` | ETF multi-asset live signal ingestion |
| `paper_run_etf_multi_asset.py` / `paper_run_etf_covered_call.py` | Daily paper-trading runners → `gold.paper_run_log` |
| `build_etf_multi_asset_paper_signal.sql` / `build_etf_covered_call_paper_signal.sql` | ETF paper signal SQL refresh (executed via db.py; the old cron ran them through the *Python interpreter* — broken since added) |
| `update_strategy_registry.py` | Syncs OOS backtest stats from `gold.strategy_backtests` into `gold.strategy_registry` (known id-space mismatch — see file header) |
| `snapshot_ticker_scores.py` | FINAL cycle step: appends today's final `strategy_ticker_scores` state to `gold.strategy_ticker_scores_history` (migration 005) — the basis for honest hit-rate/forward-return measurement |
| `backtest_metrics.py` | Importable helpers for consistent OOS metric computation |

## ⚠️ Server-side cron note (operator action)

The Hermes-profile cron script `~/.hermes/profiles/qr_etl/scripts/pipeline_b_signals.sh`
(NOT in this repo) still references the old locations:
  - explicit line: `run_gold "S9 MACD signals" "gold/strategy/s9_macd_daily.py"`
  - the `for asset in ... strategy` loop sweeping `gold/strategy/*.py`
After pulling this change those references soft-fail. Update pipeline_b to
call `agents/signals/run_signal_cycle.sh` for the signal stage (or drop the
strategy entries), mirroring what `agents/etl/daily_refresh.sh` does now.
