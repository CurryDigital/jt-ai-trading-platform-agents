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
