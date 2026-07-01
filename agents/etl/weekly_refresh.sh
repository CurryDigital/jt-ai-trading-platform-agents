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

FAILED=()
OK=()

# Generous timeout: docstrings for weekly-cadence jobs typically estimate
# 10-15 minutes for a full ticker universe. 1800s (30 min) gives headroom;
# -k 30s force-kills if a script hangs past that regardless of signal
# cooperation (same hardening applied to daily_refresh.sh's timeouts).
WEEKLY_TIMEOUT=1800

run_weekly() {
    local name="$1"
    local script="$2"
    echo "→ ${name} (budget ${WEEKLY_TIMEOUT}s)..."
    local start_ts=$(date +%s)
    if timeout -k 30s ${WEEKLY_TIMEOUT}s "${PYTHON}" "${script}"; then
        local elapsed=$(( $(date +%s) - start_ts ))
        echo "  ✅ ${name} complete (${elapsed}s)"
        OK+=("${name}")
    else
        local exit_code=$?
        local elapsed=$(( $(date +%s) - start_ts ))
        if [ $exit_code -eq 124 ]; then
            echo "  ⏱️ ${name} TIMEOUT after ${elapsed}s (budget ${WEEKLY_TIMEOUT}s)"
        else
            echo "  ⚠️ ${name} FAILED (exit $exit_code, ${elapsed}s)"
        fi
        FAILED+=("${name}")
    fi
}

echo ""
echo "🔶 WEEKLY — scanning bronze/silver/gold for '# CADENCE: weekly' tag"
echo "------------------------------------------"

# Recursive scan across all three layers — future-proof for any weekly
# script added outside bronze/yfinance/.
while IFS= read -r -d '' f; do
    if grep -q '# CADENCE: weekly' "$f" 2>/dev/null; then
        rel="${f#${WORKSPACE}/}"
        run_weekly "$rel" "$f"
    fi
done < <(find "${WORKSPACE}/bronze" "${WORKSPACE}/silver" "${WORKSPACE}/gold" -name "*.py" -print0 2>/dev/null)

if [ ${#FAILED[@]} -gt 0 ]; then
    echo "⚠️ Weekly failures: ${FAILED[*]}"
fi
echo "✅ Weekly complete (${#OK[@]} ok, ${#FAILED[@]} failed)"

echo ""
echo "=========================================="
echo "WEEKLY REFRESH COMPLETED: $(date)"
echo "Log: ${LOG_FILE}"
echo "=========================================="

exit ${#FAILED[@]}
