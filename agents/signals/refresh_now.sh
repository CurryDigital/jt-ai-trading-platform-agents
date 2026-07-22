#!/bin/bash
# refresh_now.sh — ON-DEMAND signal refresh, run whenever the operator asks.
#
# Difference from run_signal_cycle.sh (the daily cron entry):
#   - Foreground: output goes to the console, not a /tmp logfile.
#   - Quick path by default: scores → S9 → HK ingest → rebalancer →
#     history snapshot → redesign bridge. The slow ETF paper SQL + runners
#     and the registry-strategy loop are included only with --full.
#   - Same gold_layer_state gate as the cron: refuses to compute signals
#     from a broken gold layer (override with --force at your own risk).
#
# Usage:
#   bash refresh_now.sh                # quick refresh of the signal surface
#   bash refresh_now.sh --full        # everything the daily cycle runs
#   bash refresh_now.sh --force       # skip the gold_layer_state gate
#
# After it completes, the detail-page surfaces are all fresh:
#   gold.strategy_ticker_scores               (current scores)
#   gold.strategy_ticker_scores_history       (today's snapshot row)
#   consumption.strategies_signals_current    (Signals tab, current)
#   consumption.strategies_signal_history     (Signals tab, per-day history)
#   gold.paper_trades_synthetic               (Trades tab via trades_history)
#   gold.signal_evaluations / proximity       (redesign panels)

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIGNALS_DIR="${SCRIPT_DIR}"
ETL_SHARED="$(cd "${SIGNALS_DIR}/../etl/shared/scripts" && pwd)"

FULL=0
FORCE=0
for arg in "$@"; do
    case "$arg" in
        --full)  FULL=1 ;;
        --force) FORCE=1 ;;
        *) echo "unknown arg: $arg (valid: --full --force)"; exit 2 ;;
    esac
done

# ── Env + venv preamble (same contract as the cron scripts) ───────────────
ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
if [ -f "${ENV_FILE}" ]; then
    set -a && source "${ENV_FILE}" && set +a
fi
PYTHON="/home/ubuntu/.hermes/hermes-agent/venv/bin/python3"
[ -f "${PYTHON}" ] || PYTHON="$(command -v python3)"
if ! "${PYTHON}" -c "import psycopg2, dotenv" 2>/dev/null; then
    echo "FATAL: ${PYTHON} missing psycopg2/dotenv — run bootstrap_hermes_venv.sh"
    exit 70
fi
export PYTHONPATH="${ETL_SHARED}:${SIGNALS_DIR}:${PYTHONPATH:-}"
export AWS_REGION="${AWS_REGION:-ap-southeast-1}"

# ── Gold-layer gate ───────────────────────────────────────────────────────
if [ "${FORCE}" -eq 0 ]; then
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
except Exception:
    print('unknown')
" 2>/dev/null || echo unknown)
    case "${GOLD_STATE}" in
        failed|locked|stale)
            echo "⏸ gold layer state=${GOLD_STATE} — refusing to compute signals from bad data."
            echo "  Run the ETL refresh first, or re-run with --force if you accept the risk."
            exit 1
            ;;
        *) echo "gold_layer_state=${GOLD_STATE} — proceeding" ;;
    esac
fi

cd "${SIGNALS_DIR}"
FAILURES=()

step() {
    local name="$1"; local script="$2"; shift 2
    echo ""
    echo "──── ${name}"
    if timeout -k 10s 300s "${PYTHON}" "${script}" "$@"; then
        echo "──── ✅ ${name}"
    else
        echo "──── ⚠️ ${name} FAILED (exit $?)"
        FAILURES+=("${name}")
    fi
}

sql_step() {
    local name="$1"; local sql_file="$2"
    echo ""
    echo "──── ${name}"
    if timeout -k 10s 300s "${PYTHON}" -c "
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
        echo "──── ✅ ${name}"
    else
        echo "──── ⚠️ ${name} FAILED"
        FAILURES+=("${name}")
    fi
}

echo "=========================================="
echo "ON-DEMAND SIGNAL REFRESH: $(date)"
echo "mode: $([ ${FULL} -eq 1 ] && echo full || echo quick)"
echo "=========================================="

# Core signal surface, in dependency order.
step "Strategy scores"        "pipeline/build_strategy_scores.py"
step "S9 MACD signals"        "pipeline/s9_macd_daily.py"
# One recurring scan of the qr_research signal dir (replaces per-strategy scripts).
QR_SIGNAL_DIR="${QR_RESEARCH_SIGNAL_DIR:-/home/ubuntu/.hermes/profiles/qr_research/workspace}"
step "Paper-signal ingest (all)" "pipeline/ingest_paper_signal.py" --signal-dir "${QR_SIGNAL_DIR}"

if [ ${FULL} -eq 1 ]; then
    sql_step "ETF Multi-Asset signal"  "pipeline/build_etf_multi_asset_paper_signal.sql"
    sql_step "ETF Covered-Call signal" "pipeline/build_etf_covered_call_paper_signal.sql"
    step "ETF Multi-Asset paper runner"  "pipeline/paper_run_etf_multi_asset.py"
    step "ETF Covered-Call paper runner" "pipeline/paper_run_etf_covered_call.py"
    step "Registry backtest sync"        "pipeline/update_strategy_registry.py"
    step "Registry strategies (run_signals)" "strategies/run_signals.py"
fi

REBALANCER="${SIGNALS_DIR}/../etl/gold/strategy/rebuild_paper_positions.py"
[ -f "${REBALANCER}" ] && step "Position-aware paper rebalancer" "${REBALANCER}"

step "Signal history snapshot" "pipeline/snapshot_ticker_scores.py"
step "Redesign signal tables"  "strategies/build_signal_redesign.py"

echo ""
echo "=========================================="
if [ ${#FAILURES[@]} -gt 0 ]; then
    echo "⚠️ REFRESH FINISHED WITH FAILURES: ${FAILURES[*]}"
    echo "=========================================="
    exit 1
fi
echo "✅ SIGNAL REFRESH COMPLETE: $(date)"
echo "=========================================="
