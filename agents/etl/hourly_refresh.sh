#!/bin/bash
# Hourly Data Refresh Script — Medallion Architecture
# Runs: Bronze → Silver → Gold (no Consumption — daily only)
# Designed for hourly cron execution
# 2026-07-22: stage execution consolidated into run_stage.py driven by
# pipeline_manifest.json.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${SCRIPT_DIR}"
LOG_DIR="/tmp/etl_logs"
LOG_FILE="${LOG_DIR}/hourly_refresh_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "${LOG_DIR}"

exec 1>>"${LOG_FILE}" 2>&1

echo "=========================================="
echo "HOURLY REFRESH STARTED: $(date)"
echo "Workspace: ${WORKSPACE}"
echo "=========================================="

export PYTHONPATH="${WORKSPACE}/shared/scripts:${PYTHONPATH:-}"
export AWS_REGION="ap-southeast-1"

# Load environment variables from Hermes-managed env file
ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
if [ -f "${ENV_FILE}" ]; then
    set -a && source "${ENV_FILE}" && set +a
    echo "Loaded env from ${ENV_FILE}"
else
    echo "WARNING: Env file not found at ${ENV_FILE}"
fi

# Use ETL venv Python
PYTHON="/home/ubuntu/.hermes/etl-venv/bin/python3"
if [ ! -f "${PYTHON}" ]; then
    echo "FATAL: ETL venv Python not found at ${PYTHON}"
    exit 65
fi

if ! "${PYTHON}" -c "import psycopg2, dotenv" 2>/dev/null; then
    echo "FATAL: ETL venv missing psycopg2 or python-dotenv."
    echo "  ${PYTHON} cannot import psycopg2 / dotenv."
    exit 70
fi
echo "✅ ETL venv check: psycopg2 + dotenv importable"

cd "${WORKSPACE}"

# Run manifest stages
# ════════════════════════════════════════════
echo ""
echo "🚀 Running all manifest stages via run_stage.py"
echo "------------------------------------------"

"${PYTHON}" run_stage.py --cadence hourly --state-out .state.json
RUN_STAGE_EXIT=$?

echo "✅ Manifest stages complete (run_stage exit ${RUN_STAGE_EXIT})"

# ════════════════════════════════════════════
echo ""
echo "=========================================="
"${PYTHON}" "${WORKSPACE}/sync_gold_layer_state.py" && echo "✅ gold_layer_state synced to DB" || echo "⚠️ sync_gold_layer_state FAILED"

echo "HOURLY REFRESH COMPLETED: $(date)"
echo "Total failures: ${RUN_STAGE_EXIT}"
echo "Log: ${LOG_FILE}"
echo "=========================================="

# Exit non-zero if any stage failed
exit ${RUN_STAGE_EXIT}
