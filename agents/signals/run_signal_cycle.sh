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

PYTHON="/home/ubuntu/.hermes/hermes-agent/venv/bin/python3"
if [ ! -f "${PYTHON}" ]; then
    echo "FATAL: Hermes venv Python not found at ${PYTHON}"
    exit 65
fi
if ! "${PYTHON}" -c "import psycopg2, dotenv" 2>/dev/null; then
    echo "FATAL: Hermes venv missing psycopg2 or python-dotenv. Run bootstrap_hermes_venv.sh."
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

# HK Quality BlueChips paper-strategy signal ingestion (ETL-side, task t_259b9936)
run_pipeline_step "HK Quality BlueChips signal" "${SIGNALS_DIR}/../etl/gold/strategy/ingest_hk_quality_bluechips_t_259b9936.py"

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
REBALANCER="${SIGNALS_DIR}/../etl/gold/strategy/rebuild_paper_positions.py"
if [ -f "${REBALANCER}" ]; then
    run_pipeline_step "Position-aware paper rebalancer" "${REBALANCER}"
else
    echo "⚠️ Rebalancer not found at ${REBALANCER} — skipping"
    PIPELINE_FAILURES+=("rebalancer_missing")
fi

if [ ${#PIPELINE_FAILURES[@]} -gt 0 ]; then
    echo "⚠️ Signal pipeline failures: ${PIPELINE_FAILURES[*]}"
fi

echo "=========================================="
echo "SIGNAL CYCLE COMPLETED: $(date)"
echo "run_signals.py exit code: ${RC}"
echo "Log: ${LOG_FILE}"
echo "=========================================="
exit ${RC}
