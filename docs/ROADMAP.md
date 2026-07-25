# ETL + Signal pipeline — iterative roadmap

Goals for making the pipeline **expandable** (adding a strategy or data source
is a small, obvious, safe change) and **sustainable** (it stays correct without
heroics). Each goal is independently shippable and checked against
`PIPELINE_DESIGN.md`. Ordered by leverage.

## G1. Per-strategy documentation ✅ STARTED 2026-07-22
Every strategy has a `docs/strategies/<id>.md` (overview + exact buy-signal
pipeline). Authored docs for the code-driven strategies; `gen_strategy_docs.py`
generates the rest from `gold.strategy_registry`; `check_strategy_docs.py` in
CI enforces coverage. **Next:** run the generator against prod to create the
~34 semantic-strategy docs, then enrich each `signal_logic`/`exit_logic` in the
registry so the generated docs are meaningful.

## G2. One signal path per strategy (kill the mechanism sprawl) ✅ DONE 2026-07-24 (code); operator applies 010+011 on prod
Each strategy declares exactly ONE mechanism in `gold.strategy_registry.
signal_mechanism` (migration 010) and `gold.v_strategy_mechanism_audit` grades
every non-retired strategy ok/none/multiple so a signal-less strategy is flagged,
not silently all-HOLD. Migration 011 resolved the 4 formerly-'multiple': tracing
which script actually writes each strategy's `strategy_ticker_scores` proved
S9=criteria (s9_macd_daily is a separate paper tracker), US_Sector + Covered_Call
= computed, Multi_Asset = ingested — and fixed a wrong entry in 010's computed
list. A declared mechanism is now authoritative in the verdict, with
`evidence_conflict` surfacing a stale second source (e.g. an old signal_file_path)
for later cleanup. **Operator:** apply 010 then 011; the 7 verdict='none'
strategies still need a mechanism wired or retirement (that's G6 onboarding).
Remaining polish: have `run_signal_cycle.sh` dispatch on `signal_mechanism`
(today it runs every step unconditionally) — small, deferred.

## G3. Indicator correctness as a contract ✅ DONE 2026-07-24
`indicators.py` is the one true source for RSI/MACD/ATR. The FX
(`build_fx_metrics.py`) and index (`build_market_metrics.py`) builders now route
through it via `shared/scripts/price_indicators.py` (a stage-2 fill), instead of
emitting NULL macd_signal/macd_histogram/atr_14 and macd_line as an SMA
difference — so silver, FX and index agree on the math (unit-tested in
`test_indicators.py`). `tools/check_criteria_columns.py` is the DB-level guard:
it fails if any BUY criterion references a `gold.kpis_metrics` column that is
>50% NULL over the latest-per-ticker rows the scorer evaluates — the check that
would have caught the dead macd_histogram months earlier. It needs DB access, so
it runs against prod (OPERATOR_NOTES flag), not in the DB-free CI gate.

## G4. Finish the honest-upsert sweep + make it un-regressable ✅ DONE 2026-07-22
Complete the remaining metric-table `ON CONFLICT`s (sue_scores, hk_ipo_*), then
add a CI check that any `INSERT ... ON CONFLICT DO UPDATE` on a `(key,date)`
metric table refreshes every non-key column (ledger tables allow-listed). This
turns a whole bug class into a lint.

## G5. Backtest ↔ registry ↔ UI as one verifiable chain
Unify the strategy-id spaces (P0-2): `gold.strategy_registry.strategy_id` is
canonical; `strategy_backtest_runs` and the signal-agent numeric ids both map
to it explicitly. Then every number on the detail page is traceable to a
backtest run with no reverse-syncs, and "Trades (OOS): —" means genuinely no
run, not a broken join.

## G6. Onboarding is one declarative step
A new strategy = one registry row + one of {criteria rows, a signal file, a
calculator} + one doc — no dated scripts, ever. Provide `register_strategy`
for the semantic (DB) strategies mirroring the signal-agent CLI, plus a
manifest validator that rejects a strategy with no universe / no mechanism / no
doc. Expandability by construction.

## G7. Promotion gates from real evidence
With signal history (`strategy_ticker_scores_history`) and honest OOS stats,
define the numeric gates for experimental → near_golden → golden (min OOS
trades, Sharpe, max DD, live-vs-backtest tracking) in `STRATEGIES.md`, enforced
in the tier/priority display. This is the path to a defensible "golden"
strategy rather than a vibes-based label.

## Standing rule
Every new script names the principle it serves (`PIPELINE_DESIGN.md`) and adds
a check for any new invariant it introduces. No check → the next regression is
found in prod, not CI.
