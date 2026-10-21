#!/bin/bash
# run_signal_cycle.sh — Daily signal generation cron entry.
# Runs after agents/etl/daily_refresh.sh has populated the gold layer.
#
# Contract:
#   1. Verify the Hermes venv has psycopg2 + dotenv (same dep check as ETL).
#   2. Verify the gold layer is fresh enough to trust (gold_layer_state.state).
#      If state is 'failed' or 'locked', exit cleanly without writing signals.
#   3. Run strategies/run_signals.py — iterates ENABLED strategies in
#      registry.json, calls run() + save() per strategy.
#   4. Exit non-zero if any strategy crashed (run_signals.py tracks failures).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIGNALS_DIR="${SCRIPT_DIR}"
ETL_SHARED="$(cd "${SIGNALS_DIR}/../etl/shared/scripts" && pwd)"
LOG_DIR="/tmp/etl_logs"
LOG_FILE="${LOG_DIR}/signal_cycle_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "${LOG_DIR}"

exec 1>>"${LOG_FILE}" 2>&1

echo "=========================================="
echo "SIGNAL CYCLE STARTED: $(date)"
echo "Signals dir: ${SIGNALS_DIR}"
echo "ETL shared:  ${ETL_SHARED}"
echo "=========================================="

# ── PREAMBLE: env file + venv health check (mirrors daily_refresh.sh) ──
ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo "FATAL: env file not found at ${ENV_FILE}"
    exit 64
fi
set -a && source "${ENV_FILE}" && set +a

PYTHON="/home/ubuntu/.hermes/etl-venv/bin/python3"
if [ ! -f "${PYTHON}" ]; then
    echo "FATAL: ETL venv Python not found at ${PYTHON}"
    exit 65
fi
if ! "${PYTHON}" -c "import psycopg2, dotenv" 2>/dev/null; then
    echo "FATAL: ETL venv missing psycopg2 or python-dotenv. Run the ETL venv bootstrap."
    exit 70
fi

export PYTHONPATH="${ETL_SHARED}:${SIGNALS_DIR}:${PYTHONPATH:-}"
export AWS_REGION="${AWS_REGION:-ap-southeast-1}"

# ── Gate on gold-layer freshness ──────────────────────────────────────────
# If ETL marked state='failed' or 'locked', writing signals would be writing
# nonsense. Exit cleanly so cron monitoring doesn't false-alarm.
GOLD_STATE=$("${PYTHON}" -c "
import sys
sys.path.insert(0, '${ETL_SHARED}')
try:
    from db import get_connection
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute('SELECT state FROM openclaw_researcher.gold_layer_state WHERE id=1')
        row = cur.fetchone()
    conn.close()
    print(row[0] if row else 'unknown')
except Exception as e:
    print(f'error:{e}', file=sys.stderr)
    print('unknown')
" 2>/dev/null || echo unknown)

echo "gold_layer_state.state = ${GOLD_STATE}"
case "${GOLD_STATE}" in
    ready|partial)
        echo "✅ gold layer ok — proceeding"
        ;;
    failed|locked|stale)
        echo "⏸ gold layer not ready (state=${GOLD_STATE}) — skipping signal cycle"
        exit 0
        ;;
    *)
        echo "⚠️ gold layer state unknown (state=${GOLD_STATE}) — proceeding cautiously"
        ;;
esac

# ── Run the signal generation ─────────────────────────────────────────────
cd "${SIGNALS_DIR}"

# ── Signal pipeline (moved here from agents/etl/daily_refresh.sh 2026-07-10:
#    signal GENERATION is this agent's job; the ETL cron only builds data) ──
run_pipeline_step() {
    local name="$1"
    local script="$2"
    shift 2
    echo "→ ${name}..."
    if timeout -k 10s 180s "${PYTHON}" "${script}" "$@"; then
        echo "  ✅ ${name} complete"
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo "  ⏱️ ${name} TIMEOUT after 180s"
        else
            echo "  ⚠️ ${name} FAILED (exit $exit_code)"
        fi
        PIPELINE_FAILURES+=("${name}")
    fi
}

run_pipeline_sql() {
    # The old daily_refresh.sh ran these as ${PYTHON} <file>.sql — Python
    # parsing SQL, a SyntaxError on every single run since the lines were
    # added. Execute properly through the canonical db.py connection.
    local name="$1"
    local sql_file="$2"
    echo "→ ${name}..."
    if timeout -k 10s 180s "${PYTHON}" -c "
import sys
sys.path.insert(0, '${ETL_SHARED}')
from db import get_connection
sql = open('${sql_file}').read()
conn = get_connection()
try:
    with conn.cursor() as cur:
        cur.execute(sql)
    conn.commit()
finally:
    conn.close()
print('applied ${sql_file}')
"; then
        echo "  ✅ ${name} complete"
    else
        echo "  ⚠️ ${name} FAILED (exit $?)"
        PIPELINE_FAILURES+=("${name}")
    fi
}

PIPELINE_FAILURES=()

# 1. Criteria-based scoring: gold.strategy_signal_criteria × universe_tickers
#    → gold.strategy_ticker_scores
run_pipeline_step "Strategy scores" "pipeline/build_strategy_scores.py"

# Paper-strategy signal ingestion — ONE recurring scan of the qr_research
# signal directory. Replaces the per-strategy / per-batch ingest scripts
# (ingest_hk_quality_bluechips_t_259b9936.py, ingest_hk_batch_*, etc., now
# quarantined). Resolves strategy_id by name from the registry; unknown
# names are reported and skipped, never invented. Override the directory
# with QR_RESEARCH_SIGNAL_DIR.
# 2026-07-30 registry gate: after the 2026-07-29 migration of 19 strategies
# ingested -> computed, NO active strategy consumes qr_research JSON files.
# Scanning anyway hard-failed the whole cycle whenever the upstream dir was
# empty (2026-07-29 09:15 cron RED). Only run the ingest when at least one
# non-retired, non-paused strategy still has signal_mechanism='ingested';
# otherwise skip cleanly. ingest_paper_signal.py remains available.
INGESTED_ACTIVE=$("${PYTHON}" -c "
import sys
sys.path.insert(0, '${ETL_SHARED}')
try:
    from db import get_connection
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute('''SELECT COUNT(*) FROM gold.strategy_registry
            WHERE signal_mechanism = 'ingested'
              AND status NOT IN ('retired', 'paused')''')
        print(cur.fetchone()[0])
    conn.close()
except Exception as e:
    print(f'error:{e}', file=sys.stderr)
    print(-1)
" 2>/dev/null || echo -1)

echo "Active ingested strategies: ${INGESTED_ACTIVE}"
if [ "${INGESTED_ACTIVE}" = "0" ]; then
    echo "⏸️  Paper-signal ingest (all) skipped — no active strategies with signal_mechanism='ingested'"
else
    # -1 = registry probe failed: fail open (run the ingest) so a real
    # consumer is never starved by a transient DB hiccup.
    QR_SIGNAL_DIR="${QR_RESEARCH_SIGNAL_DIR:-/home/ubuntu/.hermes/profiles/qr_research/workspace}"
    run_pipeline_step "Paper-signal ingest (all)" "pipeline/ingest_paper_signal.py" --signal-dir "${QR_SIGNAL_DIR}"
fi

# 1b. Computed rotation-signal engine — regenerates gold.strategy_ticker_scores
#     for every paper strategy with signal_mechanism='computed' (incl. the 19
#     strategies migrated from ingested -> computed 2026-07-29). Runs AFTER the
#     ingest scan so computed rows are the final writer; ingest_paper_signal.py
#     skips any strategy whose registry signal_mechanism is not 'ingested'.
run_pipeline_step "Rotation signals (computed)" "pipeline/build_rotation_signals.py"

# 1c. HK IPO post-listing drift V3 — RETIRED 2026-09-18 (kanban t_ff7513a4,
#     2026-09-18 strategy review). Registry status='retired',
#     disable_paper_rebuild=TRUE; generator script
#     agents/etl/gold/strategy/hk_ipo_postlisting_drift_p1_v3_daily.py kept on
#     disk for audit but is no longer invoked here.
echo "⏸️  HK IPO drift V3 signal generation skipped — strategy RETIRED 2026-09-18 (t_ff7513a4)"

# 1d. HK IPO day-1 green momentum V1 — RETIRED 2026-09-15 (kanban t_fd837e85).
#     Research verdict: lottery-type edge (6 tail winners = +216.7pp vs 11 trades
#     net -44.6pp), OOS t-stat 1.67 below bar, last-6m cohort t-stat 0.73.
#     Registry status='retired', disable_paper_rebuild=TRUE; generator script
#     agents/etl/gold/strategy/hk_ipo_day1_green_momentum_v1_daily.py kept on
#     disk for audit but is no longer invoked here.
echo "⏸️  HK IPO day1-green V1 signal generation skipped — strategy RETIRED 2026-09-15 (t_fd837e85)"

# 1e. US VIX-spike crisis event V3 (kanban t_de0986e1) — event-driven
#     GLD/SPY 50/50 crisis sleeve; own daily generator replays the research
#     engine (vix_z60 cross >=+2, re-arm <1, next-bar-close entry, +20td
#     time exit, first-wins) with a hard seed assertion against
#     gold.strategy_backtest_trades. OBSERVER-ONLY (user HOLD 2026-09-23,
#     c1 pattern): assigned_capital=$0.00 so the rebalancer sizes every
#     position to 0 — signal flow runs for validation only, no paper
#     capital. build_rotation_signals.py skips it (no engine config), so
#     this script is the final writer of its ticker_scores.
VIX_EVENT_GEN="${SIGNALS_DIR}/../etl/gold/strategy/us_vix_spike_crisis_event_v3_daily.py"
if [ -f "${VIX_EVENT_GEN}" ]; then
    run_pipeline_step "VIX-spike event V3 signals (observer)" "${VIX_EVENT_GEN}"
else
    echo "⚠️ VIX-spike event generator not found at ${VIX_EVENT_GEN} — skipping"
    PIPELINE_FAILURES+=("vix_spike_event_v3_missing")
fi

# 2. S9 MACD daily signal generation
run_pipeline_step "S9 MACD signals" "pipeline/s9_macd_daily.py"

# 3. ETF paper-trading signal refresh + paper runners
run_pipeline_sql  "ETF Multi-Asset signal" "pipeline/build_etf_multi_asset_paper_signal.sql"
run_pipeline_sql  "ETF Covered-Call signal" "pipeline/build_etf_covered_call_paper_signal.sql"
run_pipeline_step "ETF Multi-Asset paper runner" "pipeline/paper_run_etf_multi_asset.py"
run_pipeline_step "ETF Covered-Call paper runner" "pipeline/paper_run_etf_covered_call.py"

# 4. Sync OOS backtest stats into gold.strategy_registry
run_pipeline_step "Registry backtest sync" "pipeline/update_strategy_registry.py"

if [ ${#PIPELINE_FAILURES[@]} -gt 0 ]; then
    echo "⚠️ Signal pipeline failures: ${PIPELINE_FAILURES[*]}"
fi

# ── Registry-strategy signal generation ───────────────────────────────────
"${PYTHON}" strategies/run_signals.py
RC=$?

# ── Redesign signal-consumption tables (bridge legacy signal tables → v2 views) ──
# Populates gold.signal_evaluations, gold.signal_family_performance,
# gold.signal_proximity_facts. Must run AFTER run_signals.py because it reads
# gold.strategy_ticker_scores.
if [ ${RC} -eq 0 ]; then
    echo "→ Building redesign signal tables..."
    if "${PYTHON}" strategies/build_signal_redesign.py; then
        echo "  ✅ redesign signal tables complete"
    else
        echo "  ⚠️ redesign signal tables failed"
        # Don't fail the whole cycle; legacy signal logs are already written.
    fi
else
    echo "  ⚠️ run_signals.py failed — skipping redesign signal tables"
fi

# ── Signal history snapshot (P0-3) — LAST step so it captures the day's
#    final scores from every writer above. Without this, strategy_ticker_
#    scores overwrites itself and yesterday's signals are unrecoverable. ──
run_pipeline_step "Signal history snapshot" "pipeline/snapshot_ticker_scores.py"

# ── Generic position-aware paper rebalancer (after all signal writers) ───────
# Rebuilds consumption.strategies_signals_current and gold.paper_trades_
# synthetic from gold.strategy_ticker_scores + silver.unified_prices.
# Enforces one open position per (strategy_id, ticker) and one signal per
# (strategy_id, ticker) at the DB level.
# Cadence gate (t_68b07c59): this step runs EVERY cycle so signal generation
# stays daily and idempotent, but position mutations are gated inside the
# engine on gold.strategy_registry.frequency — weekly/monthly strategies only
# close/open on the first run of a new ISO-week/calendar-month (state in
# gold.strategy_rebalance_state); daily/event strategies rebalance every run.
REBALANCER="${SIGNALS_DIR}/../etl/gold/strategy/rebuild_paper_positions.py"
if [ -f "${REBALANCER}" ]; then
    run_pipeline_step "Position-aware paper rebalancer" "${REBALANCER}"
else
    echo "⚠️ Rebalancer not found at ${REBALANCER} — skipping"
    PIPELINE_FAILURES+=("rebalancer_missing")
fi

# ── Sync paper positions into consumption.portfolio_positions_current ─────
# The /api/strategies/{id}/capital-pool endpoint reads SUM(capital)/COUNT(*)
# from that table; without this step every paper strategy reports Used=$0.
# Must run AFTER the rebalancer so it sees today's open ledger positions.
PAPER_POS_SYNC="${SIGNALS_DIR}/../etl/consumption/portfolio/sync_paper_positions_current.py"
if [ -f "${PAPER_POS_SYNC}" ]; then
    run_pipeline_step "Paper positions → portfolio_positions_current" "${PAPER_POS_SYNC}"
else
    echo "⚠️ Paper position sync not found at ${PAPER_POS_SYNC} — skipping"
    PIPELINE_FAILURES+=("paper_position_sync_missing")
fi

# ── Sync registry in_market_capital from the canonical paper ledger ─────
# t_9579ff7c: registry bookkeeping was write-once at promotion and drifted
# from the actual paper book. Recompute in_market_capital from
# gold.paper_trades_synthetic (open rows) for monitored PAPER strategies,
# zero it for unmonitored/retired PAPER rows. Must run AFTER the rebalancer.
REGISTRY_IN_MARKET_SYNC="${SIGNALS_DIR}/../etl/gold/strategy/sync_registry_in_market_capital.py"
if [ -f "${REGISTRY_IN_MARKET_SYNC}" ]; then
    run_pipeline_step "Registry in_market_capital sync" "${REGISTRY_IN_MARKET_SYNC}"
else
    echo "⚠️ Registry in_market sync not found at ${REGISTRY_IN_MARKET_SYNC} — skipping"
    PIPELINE_FAILURES+=("registry_in_market_sync_missing")
fi

if [ ${#PIPELINE_FAILURES[@]} -gt 0 ]; then
    echo "⚠️ Signal pipeline failures: ${PIPELINE_FAILURES[*]}"
fi

FINAL_RC=${RC}
if [ ${RC} -eq 0 ] && [ ${#PIPELINE_FAILURES[@]} -gt 0 ]; then
    echo "❌ Hard-failing because of pipeline failures: ${PIPELINE_FAILURES[*]}"
    FINAL_RC=1
fi

echo "=========================================="
echo "SIGNAL CYCLE COMPLETED: $(date)"
echo "run_signals.py exit code: ${RC}"
echo "pipeline failures: ${#PIPELINE_FAILURES[@]}"
echo "final exit code: ${FINAL_RC}"
echo "Log: ${LOG_FILE}"
echo "=========================================="
exit ${FINAL_RC}
