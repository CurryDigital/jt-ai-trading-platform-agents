# workspace/oneoff/ — completed one-time scripts

Scripts that ran once (or run only on explicit operator demand) and are kept
for operational history, not as part of any pipeline. Nothing in
daily_refresh.sh / hourly_refresh.sh / weekly_refresh.sh / run_daily.py /
run_signal_cycle.sh references anything in this folder — verified before
each move.

| Script | What it was for |
|---|---|
| `remediate_command_center_db.py` | One-time DB remediation for the Command Center handoff (2026-07) |
| `remediate_macro_db.py` | One-time DB remediation for the Macro tab handoff (2026-07) |
| `backfill_etf_bronze.py` / `backfill_etf_gold.py` | One-time ETF universe historical backfill |
| `inspect_etf_backfill.py` | Read-only checker for the ETF backfill |
| `ingest_etf_batch_10_2026-07-09.py` | Dated batch onboarding of 10 ETF paper strategies from qr_research's pipeline_feed.json (note: contains DB_NAME default "airtrading" typo — real db is "aitrading"; irrelevant unless re-run) |
| `hermes-verify-etf-paper-signal.{sh,sql}` | One-time verification harness for the ETF paper-signal deploy |
| `funding_rate_fix.py` + `README_funding_fix.md` | One-time funding-rate data fix |
| `test_yfinance_bootstrap.py` | One-time venv/yfinance bootstrap check |

Recurring paper-signal ingestion lives at
`agents/etl/gold/strategy/ingest_paper_signal.py` (parameterized; replaced
three single-strategy copies).

## Quarantined 2026-07-22 — metric-fabrication / provenance-laundering scripts

These three came in with the 2026-07-22 upload and were moved here because
each one, if re-run, silently corrupts the honesty of measured data. They
are kept as the historical record of what was done to prod, NOT as tools.

| Script | Why quarantined |
|---|---|
| `estimate_missing_backtest_pf.py` | Writes a HEURISTIC profit factor (`PF = 1 + return/�dd�`, sentinel 999 for all-win) into `gold.strategy_backtest_runs.profit_factor_oos` — the MEASURED column that `v_pipeline_ui_feed` serves to the frontend as "BT PF". An estimated PF displayed identically to a measured one is fabrication by presentation. The only marker is a free-text note. **Revert on prod:** `UPDATE gold.strategy_backtest_runs SET profit_factor_oos = NULL WHERE notes LIKE '%estimated_return_drawdown%';` |
| `backfill_etf_win_rate_oos.py` | REVERSE-syncs: rewrites `strategy_backtest_runs` rows to match `strategy_registry` values ("align the latest backtest row to the registry"). Data must flow runs→registry, never registry→runs — this laundering makes it impossible to verify registry stats against their source. |
| `backfill_strategy_live_data.py` | Writes SYNTHETIC trades into `gold.trade_executions` — the real execution ledger that `consumption.execution_fills` and the detail-page Trades tab read. Synthetic paper fills belong in `gold.paper_trades_synthetic` only; mixing them into the real ledger means "Live P&L" and fill counts can no longer be trusted without forensics. |

`tmp-2026-07-22/` is the batch of 20 ad-hoc probe/diagnostic scripts that
were committed to `agents/etl/tmp/` in the same upload.
