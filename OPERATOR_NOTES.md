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

### 1b. Cut daily/hourly refresh over to run_stage.py (P1-5)
The manifest engine is built, tested, and proven to enumerate EXACTLY the
scripts daily_refresh.sh runs today (equivalence diff: 0 difference, 55
scripts; the only change is deduping idempotent double-runs — resolves
flag 2). weekly_refresh.sh already delegates. Before flipping the daily/
hourly production cron, run ON THE SERVER:
    cd .../agents/etl && python3 run_stage.py --cadence daily --dry-run
compare the printed plan to a recent daily_refresh.sh log, then replace the
daily/hourly shell stage-bodies with `python3 run_stage.py --cadence <c>
--state-out .state.json` (keep the env/venv/PATH preamble and the IBKR EC2
ssh step — the runner covers python/sql steps only).

- [ ] daily/hourly cron cut over to run_stage.py after server dry-run

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
RESOLVED-ROOT-CAUSE 2026-07-17: the writer was identified — a transient
kanban recovery script (`~/.hermes/kanban/boards/trading/workspaces/
t_e8dd1cf1/refresh_pipeline.py`) wrote 3 semantic-strategy rows with
numeric ids 1/2/3 on 2026-05-29, one time. No ACTIVE writer misuses the
table; `gold.strategy_signals` remains exclusively the signal agent's
numeric-keyed table (written by `base_strategy.save()`), and semantic
strategies flow through `strategy_ticker_scores` (+ history). Remaining
operator action — delete the 3 junk rows (prod data deletion, operator
runs it):

```sql
DELETE FROM gold.strategy_signals
WHERE date = '2026-05-29'
  AND (strategy_id, strategy_name) IN
      ((1, 'cot_contrarian_extreme'),
       (2, 'cl_cot_trend'),
       (3, 'gc_cot_contrarian_inverse'));
```

Related: `strategy_backtests` rows id=2 and id=3 carry byte-identical
metrics (copy artifact from the same recovery incident) — the legacy table
should receive no new writes.

- [x] Semantic signal writer identified (dead one-off, no active misuse)
- [x] 3 junk rows deleted (operator, 2026-07-17 — verified: 0 colliding rows remain, only signal-agent names on ids 1/2/3)

### 5. OOS stats data-quality observations (post-sync, 2026-07-17)
The re-pointed sync populated 31 registry rows with real OOS stats. Two
things the numbers themselves now show:
1. **`pead_short_negative_surprise` tops the leaderboard with Sharpe 17.65,
   win rate 100%, max DD 0 — on 3 trades.** Statistically meaningless, and
   the frontend ranks by it. `strategy_backtest_runs` already computes
   `passed_trade_count` (>30) and `all_risk_gates_passed`; the tier/
   priority display (and any capital decision) should gate on those rather
   than raw Sharpe. Recommendation: expose `trade_count_oos` gates in the
   frontend ranking, or add a `gates_passed` flag to the registry sync —
   do NOT silently filter the data itself.
2. **`max_drawdown_oos` sign convention is now mixed in the registry**:
   synced rows store positive magnitudes (ABS(), the table's existing
   convention), but three pre-existing COMM_* rows carry NEGATIVE values
   with NULL win rates — written by an earlier handoff outside the sync
   (they have no backtest_runs rows, yet have stats). Normalize the sign
   (`UPDATE ... SET max_drawdown_oos = ABS(max_drawdown_oos) WHERE
   max_drawdown_oos < 0`) or re-deliver those strategies' runs properly
   via qr_research.

- [ ] Frontend/conviction gating on trade_count_oos decided
- [ ] COMM_* sign convention normalized or runs re-delivered

### 6. 2026-07-22 upload: fabricated/laundered metrics in prod (found in review)
Three scripts from the 2026-07-22 drop (now quarantined in
`workspace/oneoff/`, see its README) already ran against prod:
1. **Estimated profit factors in the measured column.** `estimate_missing_
   backtest_pf.py` wrote heuristic PF (`1 + return/|dd|`, sentinel 999)
   into `strategy_backtest_runs.profit_factor_oos`, which
   `v_pipeline_ui_feed` serves as "BT PF". Revert:
   `UPDATE gold.strategy_backtest_runs SET profit_factor_oos = NULL
    WHERE notes LIKE '%estimated_return_drawdown%';`
2. **Reverse-synced backtest rows.** `backfill_etf_win_rate_oos.py`
   rewrote 8 ETF strategies' latest backtest rows to match registry values
   — runs→registry provenance destroyed for those rows; treat their
   win_rate_oos as unverifiable until qr_research re-delivers.
3. **Synthetic trades in the real ledger.** `backfill_strategy_live_data.py`
   wrote synthetic PAPER fills into `gold.trade_executions` (read by
   execution_fills + detail-page Trades). Quantify:
   `SELECT COUNT(*) FROM gold.trade_executions te
    WHERE EXISTS (SELECT 1 FROM gold.strategy_registry sr
                  WHERE sr.strategy_id = te.strategy_id
                    AND sr.execution_mode = 'PAPER');`
   Decide: move them to paper_trades_synthetic, or add a source column
   ('real'|'synthetic') and make consumption views filter.

- [ ] Estimated PFs reverted on prod
- [ ] Reverse-synced ETF backtest rows flagged to qr_research
- [x] trade_executions synthetic rows separated or labeled — RESOLVED 2026-07-22
       migration 009 applied on prod. VERIFIED: gold.trade_executions is
       EMPTY (0 rows) — the real ledger was never actually polluted; the
       synthetic paper trades correctly live in gold.paper_trades_synthetic
       (98) / s9_paper_trades (105), their proper home. execution_source
       backfill marked 0 synthetic / 0 real (nothing to label). signal_source
       backfill worked: 94 ingested / 64 computed. consumption.execution_
       fills_real correctly returns empty (= honest "no live broker fills
       yet"). Nothing to move — populating trade_executions from the paper
       tables would be the anti-pattern.
       SEPARATE, still open: the detail page's "Live WR 0% over 3 trades"
       treats OPEN paper_trades_synthetic positions as realized losses.
       Frontend fix = compute Live WR from consumption.strategies_trades_
       history WHERE status='closed' (migration 008 exposes status), NOT
       from execution_fills_real (which stays empty until real fills exist).


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

### P1-5. Replace glob-sweeps with an explicit manifest 🟡 ENGINE DONE 2026-07-22 (`agents/etl/pipeline_manifest.json` + `run_stage.py` + CI validation; weekly_refresh.sh converted; daily/hourly shell cutover gated on a server dry-run — see below)
`for f in bronze/yfinance/*.py` is how the double-Yahoo-ingest happened,
how `ingest_yfinance_aux` got swept into a 120s timeout, and why the
`# CADENCE: weekly` marker hack exists. One manifest (per stage: script,
cadence, timeout, enabled) + one runner would replace the duplicated
`run_*` functions across daily/hourly/weekly shells and make "what runs
when" reviewable in a single diff.

### P1-6. Standardize freshness marking ✅ DONE 2026-07-22 — `freshness_guard` context manager (shared/scripts/freshness.py) + run_stage.py now stamps gold.source_freshness for EVERY manifest step whose script doesn't already self-stamp (38 previously-blind silver/gold/consumption/VIX steps now covered; 17 self-stampers keep their own source names). Complete-by-construction: any new manifest step gets freshness for free. Requires the daily/hourly cron cutover to run_stage.py (flag 1b) to take effect on the recurring path.
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
