# Operator Notes — pipeline flags & optimization backlog

Living document. Items get added by review sessions and checked off by the
operator. Last updated: 2026-07-10 (ETL + signals folder review).

---

## ⚠️ Action required

### 1. Server cron still points at old signal-script paths
`~/.hermes/profiles/qr_etl/scripts/pipeline_b_signals.sh` (lives on the
server, **outside this repo**) still references:
- `run_gold "S9 MACD signals" "gold/strategy/s9_macd_daily.py"` (explicit line)
- the `for asset in ... strategy` loop sweeping `gold/strategy/*.py`

Signal generation moved to `agents/signals/pipeline/` on 2026-07-10, so after
hermes pulls, those lines soft-fail on every run. Fix: update pipeline_b to
call `agents/signals/run_signal_cycle.sh` for the signal stage (or drop the
strategy entries). Details: `agents/signals/pipeline/README.md`.

- [ ] pipeline_b_signals.sh updated on server

---

## 🚩 Flagged, deliberately not fixed

### 2. daily_refresh.sh double-runs the gold/market builders
The gold asset loop sweeps `gold/market/*.py`, then ten of the same scripts
are re-run explicitly right after (lines under "Redesign data-related
builders"). Idempotent but wasteful (~10 redundant script executions per
daily run). Left as-is because collapsing it changes execution order — an
intent decision, not a cleanup. Options: (a) drop the explicit lines and
trust the sweep, (b) drop `market` from the sweep list and keep the explicit
ordered lines (mirrors what was done for `strategy`).

- [ ] Decision made and applied

### 3. `gold.stock_metrics` is an orphan table
Zero readers anywhere in the codebase. Its only writer was
`gold/equity/build_stock_metrics.py` — a confused script whose docstring
claimed `gold.stock_metrics` but which actually wrote
`gold.stock_metrics_history` (deleted 2026-07-10 as a duplicate writer).
The table remains in the DB untouched: dropping production tables is an
operator decision, not a cleanup side effect.

- [ ] `DROP TABLE gold.stock_metrics` (or document a reason to keep it)

### 4. `gold.strategy_signals` id-space collision (found 2026-07-17)
The diagnostic showed two DIFFERENT strategies sharing the same smallint
`strategy_id` in `gold.strategy_signals`: id=1 has rows named both
'Dual EMA crossover' (signal agent) AND 'cot_contrarian_extreme' (semantic
strategy); same for id=2 ('52-week high momentum' / 'cl_cot_trend') and
id=3 ('RSI(2) mean reversion' / 'gc_cot_contrarian_inverse'). Something —
likely a qr_research writer — inserted semantic strategies' signals using
numeric ids that collide with the signal agent's id space. Since the PK is
`(date, strategy_id)`, a same-day write from both silently overwrites one
of them. Find the semantic writer, stop it using this table (or give it
its own semantic-keyed signals table), and treat the 3 colliding history
rows as suspect. Related: `strategy_backtests` rows id=2 and id=3 carry
byte-identical metrics — a copy artifact, further evidence this legacy
table shouldn't receive new writes.

- [ ] Semantic signal writer identified and moved off gold.strategy_signals


---

## 🔭 Optimization backlog (from the 2026-07-10 full etl+signals review)

Ordered by impact. P0 = prevents the bug classes we actually hit this month.

### P0-1. CI syntax/reference gate ✅ DONE 2026-07-10 (`.github/workflows/pipeline-checks.yml` + `tools/check_pipeline_refs.py`)
The `${PYTHON} <file>.sql` bug (Python parsing SQL, failing every run) and
the dangling `ingest_small_cap_credit_spread.py` reference both shipped
because nothing checks the repo at commit time. A minimal GitHub Action
would have caught both:
- `python3 -m py_compile` over all `*.py`
- `bash -n` over all `*.sh`
- `python3 agents/signals/tests/test_registry_loader.py`
- a script that greps every path passed to `run_bronze/run_silver/run_gold/
  run_consumption/run_pipeline_step` in the refresh shells and asserts the
  file exists and its extension matches the runner.

### P0-2. Unify the three strategy-id spaces ✅ RESOLVED 2026-07-17 — diagnostic proved NO mapping exists: smallint ids 1/2/3 in strategy_backtests are signal-agent artifacts (1=Dual EMA, 2=52wk-high, 3=RSI(2), confirmed via strategy_signals.strategy_name + registry.json); registry_strategy_id stays NULL by design. Real OOS runs live in `gold.strategy_backtest_runs` (semantic-keyed, 59 strategies) and `update_strategy_registry.py` now syncs from there. The 006 bridge remains for any future operator-mapped legacy row.
`registry.json` uses numeric ids (1–20), `gold.strategy_registry` uses
semantic varchar ids (`btc_funding_mean_rev_short`), and
`gold.strategy_backtests` uses smallint ids. Consequences observed live:
`update_strategy_registry.py`'s sync matches 0 rows (frontend shows
"Trades (OOS): —" for nearly every strategy), and family mapping falls back
to keyword guessing. Recommendation: make `gold.strategy_registry.strategy_id`
canonical; add a varchar `strategy_id` to `strategy_backtests`; store the
semantic id in `registry.json` entries alongside the numeric signal id.

### P0-3. Signal history ✅ DONE 2026-07-10 (migration 005 + `snapshot_ticker_scores.py` as final cycle step) — apply migration 005 on prod
`gold.strategy_ticker_scores` is a single-row-per-(strategy, ticker) upsert —
every run overwrites the previous score. There is **no record of what the
system's signal was yesterday**, which makes signal-quality measurement
(hit rate, forward returns — the thing signal_family_performance is supposed
to show honestly) impossible by construction. Add an append-only
`gold.strategy_ticker_scores_history (strategy_id, ticker, date, ...)`
written each cycle; then `signal_family_performance` can be computed from
realized outcomes instead of staying empty (or worse, fabricated).

### P1-4. Batch the row-by-row upserts 🟡 STARTED 2026-07-10 (yfinance prices done via execute_values + savepoint fallback; COT loaders and gold builders remain)
`_upsert_prices` (yfinance), the COT loaders, and several gold builders
iterate DataFrames calling `cur.execute` per row — 10k+ round trips per
daily run. `psycopg2.extras.execute_values` is a drop-in ~10–50× speedup
and directly shrinks the daily window in which timeouts fire.

### P1-5. Replace glob-sweeps with an explicit manifest
`for f in bronze/yfinance/*.py` is how the double-Yahoo-ingest happened,
how `ingest_yfinance_aux` got swept into a 120s timeout, and why the
`# CADENCE: weekly` marker hack exists. One manifest (per stage: script,
cadence, timeout, enabled) + one runner would replace the duplicated
`run_*` functions across daily/hourly/weekly shells and make "what runs
when" reviewable in a single diff.

### P1-6. Standardize freshness marking 🟡 STARTED 2026-07-10 (`freshness_guard` context manager added to shared/scripts/freshness.py; ingest_yfinance_prices.py converted as the reference — remaining scripts to migrate opportunistically)
`gold.source_freshness` coverage is opt-in per script — some mark, some
don't (ingest_yfinance_prices.py only gained it in this review). Wrap it
once in `shared/scripts` (context manager or decorator) and require it via
the P0-1 CI grep, so the staleness monitor's picture is complete rather
than "fresh where instrumented".

### P1-7. Skip all-NULL bronze rows at ingest ✅ DONE 2026-07-10 (equities + commodity futures)
The 2026-06-19 (Juneteenth) row landed in `bronze.yf_prices` with every
OHLC field NULL and then blocked gold's NOT NULL filter for weeks. The
COALESCE upsert fix stops the freezing, but ingest should simply not insert
a row whose `close` is None — holidays produce no bar, and a missing row is
more honest than a NULL row.

### P2-8. Move `gold_layer_state` out of `openclaw_researcher`
The pipeline's own health flag lives in the legacy multi-agent schema —
already caused one false "table does not exist" diagnosis. Migrate to
`gold.pipeline_state` (or an `ops` schema) with a compatibility view during
transition.

### P2-9. Resolve the COT expansion conflict
`workspace/cot_expansion/cot_ingest.py` (GC/CL/ES) uses a contrarian
z-score sentiment convention; the live EURO FX path in `gold_builder.py`
uses a trend-following net-position threshold — opposite meanings in the
same `sentiment` column. Meanwhile the staleness monitor checks CL/GC/ES
COT with an 8-day SLA, so it alarms forever on instruments nothing ingests.
Either unify the methodology and deploy the expansion, or delete the
workspace script and the dead staleness checks.

### P2-10. IBKR surface area
Six bronze scripts + an EC2 runner + a tunnel service + a watchdog, with
`bronze.ibkr_positions_live` written by two scripts (`ingest_ibkr.py` and
`ingest_ibkr_tws.py`). Document which path is authoritative (EC2 runner vs
local), and collapse the position writers to one.

### P2-11. Regime model hygiene
`train_hmm.py` retrains daily and overwrites `hmm_model.pkl` in place — no
versioning, no drift tracking, and the Hurst sanity test prints
"WARNING: may indicate broken Hurst function" on every single run (verified
in live logs), which trains operators to ignore warnings. Version the model
artifact by date and either fix or explicitly accept-and-silence the Hurst
check.

### P2-12. Freshness gate inside strategy scoring
`build_strategy_scores.py` scores whatever `latest_kpis` row exists, however
old. The signal cycle gates on `gold_layer_state`, but a per-run assert
("kpis max(date) within N trading days, else refuse to score") would stop
stale-data signals at the last line of defense too.
