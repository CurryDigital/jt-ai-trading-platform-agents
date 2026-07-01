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
"${PYTHON}" strategies/run_signals.py
RC=$?

echo "=========================================="
echo "SIGNAL CYCLE COMPLETED: $(date)"
echo "run_signals.py exit code: ${RC}"
echo "Log: ${LOG_FILE}"
echo "=========================================="
exit ${RC}
