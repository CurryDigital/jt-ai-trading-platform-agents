#!/bin/bash
# Weekly Data Refresh Script — long-running, low-cadence sources.
#
# Companion to daily_refresh.sh. Runs any bronze/silver/gold script tagged
# with the '# CADENCE: weekly' marker anywhere in its file — these are jobs
# that legitimately take longer than the 120s daily bronze timeout allows
# (e.g. earnings + institutional holdings for the full ticker universe,
# ~10-15 minutes) and were never meant to run inside the daily cron.
#
# 2026-07-01: created after ingest_yfinance_aux.py (self-documented as a
# "run separately via cron weekly" job) was found being swept into
# daily_refresh.sh's naive bronze/yfinance/*.py glob, blowing the daily
# pipeline's time budget every run. daily_refresh.sh now explicitly skips
# any '# CADENCE: weekly'-tagged file; this script is where those files run
# instead.
#
# Same fail-fast preamble as daily_refresh.sh: exits loudly on missing env
# file / venv / deps rather than silently doing nothing.
#
# Operator action required: this script has NO cron entry of its own yet.
# Add one, e.g. Sunday 03:00 UTC (11:00 SGT):
#     0 3 * * 0  /bin/bash /path/to/agents/etl/weekly_refresh.sh

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${SCRIPT_DIR}"
LOG_DIR="/tmp/etl_logs"
LOG_FILE="${LOG_DIR}/weekly_refresh_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "${LOG_DIR}"

exec 1>>"${LOG_FILE}" 2>&1

echo "=========================================="
echo "WEEKLY REFRESH STARTED: $(date)"
echo "Workspace: ${WORKSPACE}"
echo "=========================================="

export PYTHONPATH="${WORKSPACE}/shared/scripts:${PYTHONPATH:-}"
export AWS_REGION="ap-southeast-1"

# ── PREAMBLE: same fail-fast contract as daily_refresh.sh ─────────────────
ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
if [ ! -f "${ENV_FILE}" ]; then
    echo "FATAL: env file not found at ${ENV_FILE}"
    exit 64
fi
set -a && source "${ENV_FILE}" && set +a
echo "Loaded env from ${ENV_FILE}"

PYTHON="/home/ubuntu/.hermes/hermes-agent/venv/bin/python3"
if [ ! -f "${PYTHON}" ]; then
    echo "FATAL: Hermes venv Python not found at ${PYTHON}"
    exit 65
fi
if ! "${PYTHON}" -c "import psycopg2, dotenv" 2>/dev/null; then
    echo "FATAL: Hermes venv missing psycopg2 or python-dotenv."
    echo "  Run: bash ${WORKSPACE}/../../bootstrap_hermes_venv.sh"
    exit 70
fi
echo "✅ Hermes venv check: psycopg2 + dotenv importable"

cd "${WORKSPACE}"

# 2026-07-22: weekly steps are now declared in pipeline_manifest.json
# (cadence: "weekly") and executed by run_stage.py — the same runner the
# daily/hourly stages use. This replaced the '# CADENCE: weekly' comment
# scan: a step's cadence is data in the manifest, not a marker grepped out
# of source files. Adding a weekly job = one manifest entry, reviewable in
# one diff. The runner applies each step's own timeout (aux = 1800s) and a
# +10s SIGKILL grace, and returns non-zero on any failure.
export PYTHON
"${PYTHON}" run_stage.py --cadence weekly
RC=$?

echo ""
echo "=========================================="
echo "WEEKLY REFRESH COMPLETED: $(date)"
echo "Log: ${LOG_FILE}"
echo "=========================================="

exit ${RC}
