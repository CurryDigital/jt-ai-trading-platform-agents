#!/bin/bash
# Daily Data Refresh Script — Medallion Architecture
# Runs: Bronze → Silver → Gold → Consumption
#
# Fail-fast contract (2026-06-22):
#   - Exits non-zero immediately if the env file is missing OR the Python
#     venv is missing psycopg2 / python-dotenv. Cron was previously running
#     a 100%-failing pipeline silently, writing "fresh" to gold_layer_state
#     and reporting success. See README.md "honest state" for rationale.
#   - Per-stage success/failure is tracked and written to .state.json by
#     run_stage.py. sync_gold_layer_state.py reads that file and updates the
#     DB. If the script aborts before the writer runs, gold_layer_state defaults
#     to 'stale' instead of being left lying.
#
# 2026-07-22: stage execution consolidated into run_stage.py driven by
# pipeline_manifest.json. The IBKR EC2 ssh runner remains outside the manifest
# because run_stage covers python/sql only.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${SCRIPT_DIR}"
LOG_DIR="/tmp/etl_logs"
LOG_FILE="${LOG_DIR}/daily_refresh_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "${LOG_DIR}"

exec 1>>"${LOG_FILE}" 2>&1

echo "=========================================="
echo "DAILY REFRESH STARTED: $(date)"
echo "Workspace: ${WORKSPACE}"
echo "=========================================="

export PYTHONPATH="${WORKSPACE}/shared/scripts:${PYTHONPATH:-}"
export AWS_REGION="ap-southeast-1"

# ── PREAMBLE: fail loudly on misconfigured environment ────────────────────
# Load environment variables from Hermes-managed env file. We treat a missing
# env file as fatal — the previous behaviour silently continued with whatever
# env the cron inherited, which caused months of stale data dashboards.
ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo "FATAL: env file not found at ${ENV_FILE}"
    echo "Hermes profile may be misconfigured. Run bootstrap_hermes_venv.sh."
    exit 64  # EX_USAGE
fi
set -a && source "${ENV_FILE}" && set +a
echo "Loaded env from ${ENV_FILE}"

# Use ETL venv Python — but verify it actually exists.
PYTHON="/home/ubuntu/.hermes/etl-venv/bin/python3"
if [ ! -f "${PYTHON}" ]; then
    echo "FATAL: ETL venv Python not found at ${PYTHON}"
    echo "Run /home/ubuntu/.hermes/etl-venv/bin provisioning to fix."
    exit 65  # EX_DATAERR
fi

# Verify required Python deps are importable. If not, the entire pipeline
# would otherwise crash silently inside each stage. Better to fail here with
# one clear message than 30 ModuleNotFoundError tracebacks scattered in logs.
if ! "${PYTHON}" -c "import psycopg2, dotenv" 2>/dev/null; then
    echo "FATAL: ETL venv missing psycopg2 or python-dotenv."
    echo "  ${PYTHON} cannot import psycopg2 / dotenv."
    exit 70  # EX_SOFTWARE
fi
echo "✅ ETL venv check: psycopg2 + dotenv importable"

cd "${WORKSPACE}"

# IBKR EC2 ssh runner is NOT covered by the python/sql manifest runner.
FAILED_BRONZE=()

# ════════════════════════════════════════════
echo ""
echo "🔶 BRONZE — IBKR EC2 runner"
echo "------------------------------------------"

# Interactive Brokers (positions/portfolio + live TWS sync)
# Runs on EC2 gateway directly to avoid IP mismatch with TWS session
echo "Running IBKR ingestion on EC2 gateway..."
ssh -i ~/.ssh/ibkr_ec2.pem -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@52.74.14.181 '~/run_ibkr_etl.sh' 2>&1 | while read line; do echo "  [EC2] $line"; done
IBKR_EC2_EXIT=${PIPESTATUS[0]}
if [ $IBKR_EC2_EXIT -ne 0 ]; then
    FAILED_BRONZE+=("IBKR:EC2_runner")
    echo "  ⚠️ IBKR EC2 runner failed (exit $IBKR_EC2_EXIT)"
fi

# ════════════════════════════════════════════
echo ""
echo "🚀 Running all manifest stages via run_stage.py"
echo "------------------------------------------"

"${PYTHON}" run_stage.py --cadence daily --state-out .state.json
RUN_STAGE_EXIT=$?

echo "✅ Manifest stages complete (run_stage exit ${RUN_STAGE_EXIT})"

# ════════════════════════════════════════════
echo ""
echo "=========================================="

# sync_gold_layer_state.py reads the .state.json produced by run_stage.py.
"${PYTHON}" "${WORKSPACE}/sync_gold_layer_state.py" \
    && echo "✅ gold_layer_state synced to DB" \
    || echo "⚠️ sync_gold_layer_state FAILED"

TOTAL_FAILS=$(( ${RUN_STAGE_EXIT:-0} + ${IBKR_EC2_EXIT:-0} ))
echo "DAILY REFRESH COMPLETED: $(date)"
echo "Total failures: ${TOTAL_FAILS} (run_stage exit ${RUN_STAGE_EXIT}, IBKR EC2 exit ${IBKR_EC2_EXIT})"
echo "Log: ${LOG_FILE}"
echo "=========================================="

# Exit non-zero if the manifest runner or the IBKR EC2 runner failed
exit ${TOTAL_FAILS}
