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

### 1d. Apply migration 010 + resolve strategy signal-mechanism (ROADMAP G2)
Migration 010 adds gold.strategy_registry.signal_mechanism and
gold.v_strategy_mechanism_audit. After applying, run:
    SELECT * FROM gold.v_strategy_mechanism_audit WHERE verdict <> 'ok';
- verdict='none'   → strategy has NO signal path (all-HOLD forever). Wire a
  mechanism (criteria rows / signal file / a calculator) or retire it.
- verdict='multiple' → two writers (e.g. S9 = criteria AND s9_macd_daily.py).
  Pick ONE: either drop the criteria rows (let the calculator own it) or make
  the calculator exit-only. Then set signal_mechanism explicitly.
The migration auto-sets only the unambiguous 'ok' strategies; none/multiple
are left for this decision (never silently picked).

UPDATE 2026-07-24 — migration 011 resolves the 4 'multiple' (evidence-based,
traced from which script writes each strategy's strategy_ticker_scores):
  S9_MACD_Momentum_V2               -> criteria  (s9_macd_daily writes its own
                                                  s9_* tables, not the scores)
  ETF_US_Sector_Relative_Momentum   -> computed  (calc_etf_relative_momentum.py)
  ETF_Covered_Call_Income_Rotation  -> computed  (build_etf_covered_call_paper_signal.sql)
  ETF_Multi_Asset_Tactical_Allocation -> ingested (ingest_etf_multi_asset_live_signal.py;
                                                    paper_run only READS scores)
011 also fixes a wrong entry in 010's computed list (S9 + Multi_Asset were
mislabelled), makes a DECLARED mechanism authoritative in the verdict, and adds
evidence_conflict (declared but a stale 2nd source remains). Apply 010 THEN 011:
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_setup/migrations/010_signal_mechanism.sql
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_setup/migrations/011_resolve_signal_mechanism.sql
    SELECT strategy_id, declared, verdict, evidence_conflict FROM gold.v_strategy_mechanism_audit ORDER BY verdict, strategy_id;
After 011: 0 'multiple'. evidence_conflict flags US_Sector + Covered_Call — clear
their stale gold.strategy_registry.signal_file_path (read by NO live code) in a
reviewed follow-up. The 7 verdict='none' (3×COMM_*, earnings_vol_crush_carry,
3×US_STK_*) have NO signal path — wire criteria/a calculator/a signal file, or
retire them (ROADMAP G6). Not resolved here (per-strategy onboarding decision).

UPDATE 2026-07-24 — migration 012 finishes the cleanup (apply after 011):
    psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f db_setup/migrations/012_signal_mechanism_cleanup.sql
  * Clears the stale signal_file_path on the 2 computed ETFs -> evidence_conflict 0.
  * Adds has_universe/has_backtest to the audit view, then AUTO-RETIRES only the
    inert 'none' orphans: no backtest run AND no ticker scores (a bare
    universe_tickers watchlist is NOT footprint — the 3 COMM_* carry a universe
    yet have no backtest, no scores, no mechanism, and zero repo references).
    The DB picks; expected the 3 COMM_*. Reversible via retired_at=NULL. The
    remaining 'none' (earnings_vol_crush_carry + the 3 US_STK_*) all have a
    backtest run = real but unwired, left flagged for wiring (G6).
  Verify:  SELECT strategy_id, retirement_reason FROM gold.strategy_registry WHERE retirement_reason LIKE 'G2/012%';
           SELECT strategy_id, has_universe, has_backtest FROM gold.v_strategy_mechanism_audit WHERE verdict='none';

- [ ] migrations 011 + 012 applied; 0 'multiple' and 0 evidence_conflict
- [ ] auto-retired orphans reviewed (expected: 3 COMM_*); reversible if wrong
- [ ] remaining verdict='none' (real, unwired) scheduled for wiring (G6)

### 1e. Post-refresh indicator/criteria health checks (ROADMAP G3)
After a gold refresh (which now runs the FX/index stage-2 indicator fill), run
against prod to confirm no BUY criterion points at a dead (mostly-NULL) column
— the check that would have caught the killed macd_histogram:
    python3 tools/check_criteria_columns.py       # exit 1 => a criterion column is >50% NULL
Also spot-check the newly-filled indicators are populated (not NULL):
    SELECT COUNT(*) FILTER (WHERE macd_histogram IS NOT NULL) AS nn, COUNT(*)
      FROM gold.fx_metrics WHERE date > CURRENT_DATE - 30;
    SELECT COUNT(*) FILTER (WHERE macd_hist IS NOT NULL) AS nn, COUNT(*)
      FROM gold.index_metrics WHERE date > CURRENT_DATE - 30;
Note: the stage-2 fill reads a 420-day warmup back from the gold table itself,
so on a table with <~30 days of history macd/atr stay NULL by design (never
fabricated) until enough history accumulates.

Prod test 2026-07-25 (hermes) findings:
- gold.index_metrics: macd_hist/atr_14 went 0/224 -> 224/224 after re-running
  build_market_metrics.py. G3 fill proven end-to-end on real data.
- gold.fx_metrics: last row is 2026-06-17, so nothing in the 30-day window —
  the fill wrote 255 historical rows correctly but bronze.fx_prices ingestion
  is STALE (~5 weeks). Not a builder bug; a data-feed gap (see flag 7 below).
- check_criteria_columns.py FAILED (exit 1): gold.kpis_metrics.macd_histogram
  is 99.4% NULL over 924 tickers. EXPECTED until the *equity* path is re-run:
  the S1 fix lives in silver/compute_technical_indicators.py ->
  gold/equity/build_equity_kpis.py, neither of which has run on prod since the
  fix. Reviving macd_histogram (and every MACD BUY) requires, in order:
      cd agents/etl
      python3 silver/compute_technical_indicators.py   # writes silver.technical_indicators
      python3 gold/equity/build_equity_kpis.py          # copies macd_histogram -> gold.kpis_metrics
      python3 ../signals/pipeline/build_strategy_scores.py   # HOLD->BUY revival
  then re-run tools/check_criteria_columns.py (expect green).

- [x] check_criteria_columns.py green on prod — VALIDATED 2026-07-25 (hermes):
      after re-running the fixed silver indicators + equity kpis, macd_histogram
      went 99.4% -> 5.6% NULL (872/924 tickers), volume_ratio 4.3% NULL, guard
      EXIT 0. The residual 5.6% is honest insufficient-history tickers, not a bug.
- [x] kpis_metrics.macd_histogram revived + S9 BUY restored — VALIDATED 2026-07-25:
      S9_MACD_Momentum_V2 went 0 BUY / 50 HOLD -> 1 BUY (TMO, score 100) / 49 HOLD.
      NOTE: this SUSTAINS only once the fixed scripts run on the recurring path —
      i.e. after PR #8 is deployed AND the daily refresh runs compute_technical_
      indicators.py + build_equity_kpis.py (they already do; flag 1b cutover just
      changes HOW they're invoked, not whether). Re-check with the guard weekly.

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

### 1c. build_pipeline_feed.py is not run by any repo refresh shell
The dry-run gate (2026-07-22) caught that consumption/pipeline/build_pipeline_
feed.py — which reads gold.v_pipeline_ui_feed and writes the frontend Pipeline
UI's pipeline_feed.json — is NOT in daily_refresh.sh's consumption sweep
(command lab performance portfolio market — no 'pipeline') and not in any
other repo shell. It was wrongly added to the daily manifest; removed to keep
the cutover behavior-preserving. Open question: does the server-side
pipeline_b_signals.sh (outside repo) run it? If NOTHING runs it, the frontend
Pipeline feed is stale and it should be added back to the daily manifest as a
deliberate one-line change (it's a genuine gap, just not part of the cutover).

- [ ] Confirm whether build_pipeline_feed.py runs anywhere; if not, add to daily manifest

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

### 7. bronze.fx_prices ingestion is stale (found 2026-07-25 prod test)
gold.fx_metrics' latest row is 2026-06-17 — ~5 weeks stale as of the test.
The G3 stage-2 fill wrote 255 historical FX rows correctly, but there is no
recent data to indicate: bronze.fx_prices (and/or bronze.ibkr_fx_bars) isn't
being updated by the ingestion job. This is a data-feed gap, not a builder
bug — the FX MACD/ATR columns will populate for recent dates automatically
once the feed resumes. Diagnose the FX ingestion cron / IBKR FX bar puller.

- [ ] FX price ingestion confirmed running (bronze.fx_prices fresh) or gap explained


---

## 🐞 Signal-correctness bugs found & fixed (2026-07-22 internal review)

Deep read of the actual signal-generation MATH (not process/plumbing) — the
root causes of "buy signals / metrics / backtest figures missing". Fixed in
code; each needs a real-DB run to take effect (indicators must recompute, then
the scorers re-run).

### S1. Technical indicators were NULL / SMA-not-EMA / 30-day window (ROOT CAUSE)
`silver/compute_technical_indicators.py` (rewritten):
- `rsi_14`, `macd_signal`, `macd_histogram`, `atr_14` were hardcoded `NULL`.
  build_equity_kpis copies these into gold.kpis_metrics, so **macd_histogram
  was NULL everywhere** — every MACD criterion (S9's `macd_histogram >= 0.1`,
  cond_macd_bullish, s012_tech_momentum) silently never fired. Biggest reason
  MACD strategies showed all-HOLD.
- `ema_12`/`ema_26`/`macd_line` used AVG() = SMA, not EMA.
- 30-day load window made `sma_50`/`sma_200` impossible (~21 rows for a
  "200-day" average) → cond_above_sma200, golden/death cross, price_vs_sma200
  all wrong.
- ON CONFLICT didn't refresh macd_*/ema_*/rsi_14/volume_ratio → stale on re-run.
Now: pure-Python `shared/scripts/indicators.py` (Wilder RSI/ATR, EMA MACD),
unit-tested (`tests/test_indicators.py`, 7/7, incl. Wilder RSI vs classic
~70.5), 420-day warmup, recent-tail write, full-column ON CONFLICT.

### S2. S9 recomputed MACD with SMA (divergent 2nd definition)
`s9_macd_daily.py::find_signals` now reads macd_histogram/volume_ratio from
gold.kpis_metrics — one MACD definition, consistent with the criteria scorer.

### S3. ETF relative-momentum: 3 bugs
`gold/strategy/calc_etf_relative_momentum.py`:
- HARDCODED PLAINTEXT DB PASSWORD in source → now uses shared db.py.
- Lookbacks used trading-day counts (21/63/126/252) as calendar-day deltas
  ("1m" ≈ 15 trading days, "12m" ≈ 8.3 months) → now 30/91/182/365 calendar.
- fetch_universe read from the output table (strategy_ticker_scores), empty
  after any truncate → now reads strategy_registry.universe_tickers.

### S4. Incomplete ON CONFLICT across gold builders (systemic — every re-run)
Most gold builders re-insert a rolling window (last 14–90 days) each run, so
they hit ON CONFLICT for all but the newest date. Their DO UPDATE clauses
refresh only a handful of the inserted columns, so recomputed indicators and
derived flags stay STALE on ~13 of every 14 dates (and on same-day re-runs /
the double-run). Fixed so far:
- `gold/equity/build_equity_kpis.py` → kpis_metrics (9/56 → all 56). ROOT of
  the signal path; also unblocks the corrected silver MACD/RSI propagating.
- `gold/market/build_market_metrics.py` → index_metrics (5/32 → all 32).

All metric-table upserts completed 2026-07-22 (column-match verified each):
kpis_metrics, index_metrics, crypto_kpis, stock_metrics_history,
commodity_futures, market_sentiment_daily, fx_metrics.
STILL to do (lower priority):
- `build_earnings_signals.py` → sue_scores         (4/8)
- `build_ipo_data.py`         → hk_ipo_* (reference data)

Do NOT blanket-refresh the LEDGER/state tables — their partial update is
INTENTIONAL (rewriting an open position's entry_price/entry_date would corrupt
the trade record):
- `rebuild_paper_positions.py` → paper_trades_synthetic (entry_* immutable)
- `build_portfolio_snapshot.py` → ibkr_positions_live

### Also still NULL (same class as S1, different tables)
- `build_fx_metrics.py` and `build_market_metrics.py`(index) hardcode
  macd_signal/macd_histogram (and FX rsi_14) to NULL and use AVG()=SMA. No
  signal reads fx_metrics today, but any FX/index MACD criterion would be
  dead. Port to shared/scripts/indicators.py when those strategies go live.

### Still open (found, not fixed — needs decisions)
- `build_strategy_scores` only scores strategies with strategy_signal_criteria
  rows; most registry strategies have none, so they depend on file-ingest or a
  dedicated calculator. Ones with neither are all-HOLD by construction — use
  `tools/audit_strategy_consistency.py` to see each strategy's mechanism.
- rebalancer publishes `signal_strength == confidence_score` (both score/100)
  — meaningless duplication; confidence should measure something distinct.

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
