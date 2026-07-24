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

## G2. One signal path per strategy (kill the mechanism sprawl) 🟡 STARTED 2026-07-22 (migration 010: signal_mechanism column + v_strategy_mechanism_audit; docs/generator wired. Operator: apply 010, resolve none/multiple)
Today a strategy's BUY can come from criteria, a dedicated calculator, a
signal-file ingest, or two of those at once (S9 has both). Make each strategy
declare exactly ONE mechanism in the registry (`signal_mechanism` column), and
have `run_signal_cycle.sh` dispatch on it. Then `audit_strategy_consistency.py`
becomes a hard gate: every non-retired strategy must have a working mechanism
or it's flagged, not silently all-HOLD.

## G3. Indicator correctness as a contract
`indicators.py` is now the one true source for RSI/MACD/ATR. Route the FX and
index metric builders through it too (they still emit NULL macd / SMA-as-EMA),
and add a DB-level check that no strategy criterion references a column that is
>50% NULL in `gold.kpis_metrics` (that check would have caught the dead
macd_histogram months earlier).

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
