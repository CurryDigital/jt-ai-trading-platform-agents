# Pipeline Design Goal — signal + ETL north star

This is the reference every change to `agents/etl/` and `agents/signals/`
checks against. It exists because the same handful of root causes produced
almost every incident this engagement (fabricated dashboard data, frozen
signals, double-ingests, reverse-synced metrics, SQL-fed-to-Python). The
goal is to make each *class* impossible, not to keep point-fixing instances.

## The six principles

### 1. Honest by construction
Never present derived, estimated, or synthetic data as measured. Empty beats
fake — a quiet day must look quiet. Every metric that reaches the frontend
carries its **provenance** so an estimate can never be mistaken for a
measurement.
- Killed by this session: demo BUY signals, `estimate_missing_backtest_pf.py`
  (heuristic PF in the measured column), `backfill_strategy_live_data.py`
  (synthetic fills in the real ledger).
- Enforced by: provenance columns (`execution_source`, `signal_source`,
  migration 009) + `metric_valid_flag` in `v_pipeline_ui_feed`.

### 2. One declarative path per mechanism
A strategy is *declared* once; onboarding adds data, never a new script. The
recurring failure was a bespoke dated ingest script per strategy/batch. There
are exactly a few signal mechanisms — each has ONE generic implementation:
- `computed`   → criteria (`build_strategy_scores.py`), or a dedicated
  recurring calculator (`s9_macd_daily.py`, `calc_etf_relative_momentum.py`,
  ETF paper runners).
- `ingested`   → research JSON files via `ingest_paper_signal.py --signal-dir`
  (one scan, all files; unknown strategies reported, never invented).
Adding a strategy = a registry row + (criteria rows | a signal file). No code.

### 3. Data flows one direction
bronze → silver → gold → consumption; backtest_runs → registry → UI. Never
backwards. `backfill_etf_win_rate_oos.py` (registry → backtest_runs) is the
anti-pattern: it destroyed the ability to verify a stat against its source.

### 4. Freshness is enforced and visible
Every source stamps `gold.source_freshness` (via `freshness_guard`); every
consumer can see age. Stale is a *state*, never hidden. Signals computed from
a stale gold layer are refused at the gate (`gold_layer_state`), not silently
produced.

*Implementation:* `run_stage.py` stamps `gold.source_freshness` for every
manifest step whose script doesn't self-stamp — so coverage is complete by
construction, not opt-in. Scripts that self-stamp (bronze ingesters) keep
their own meaningful source names; the runner fills the rest.

### 5. Explicit over implicit
No glob-sweep-the-directory-and-run-everything. That caused the double-Yahoo
ingest, the aux-script timeout, and the `# CADENCE: weekly` marker hack. What
runs, when, and with what timeout is declared, and reviewable in one diff.
(Target: a stage manifest — see backlog P1-5.)

### 6. Contracts are machine-checked
Cross-layer breaks (SQL fed to the Python interpreter, references to deleted
scripts, tier/folder mismatch, retired-id reuse) are caught by CI before
merge, not by prod at 3am. `tools/check_pipeline_refs.py` +
`pipeline-checks.yml` + the registry-loader tests are the beginning; every
new invariant gets a check.

## Target state per side

### Signal agent (`agents/signals/`)
- `strategies/registry.json` is the single source of truth (tiers enforced,
  ids retired, loader-validated).
- `pipeline/` holds the generic generators; no per-strategy scripts.
- Every generator stamps provenance + freshness and reports consistently
  `(strategy_id, n_signals, mechanism)`.
- `run_signal_cycle.sh` (cron) and `refresh_now.sh` (on demand) run the SAME
  ordered steps behind the SAME gold-layer gate.
- Append-only history (`strategy_ticker_scores_history`) makes signal quality
  measurable; the detail page reads history, not just the latest snapshot.

### ETL agent (`agents/etl/`)
- One writer per table. Duplicate/confused writers (`build_stock_metrics`,
  the double yfinance ingesters, two `backtest_metrics`) are gone.
- Every bronze ingester: skip no-bar rows, COALESCE-upsert (never freeze a
  column at NULL), batch with `execute_values`, stamp freshness via
  `freshness_guard`.
- One-offs live in `workspace/oneoff/`, never in the pipeline root.
- Migrations are numbered, idempotent, paired with a `_verify`.

## How to use this doc
When adding or changing a script, name which principle it serves. If a change
violates one (e.g. a new per-strategy ingest script, a metric written without
provenance, a backwards data flow), it doesn't merge — it gets redesigned to
fit, or the principle gets an explicit, documented exception here.
