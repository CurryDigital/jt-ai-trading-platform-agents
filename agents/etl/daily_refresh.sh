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
#     write_pipeline_state.py. sync_gold_layer_state.py reads that file
#     and updates the DB. If the script aborts before the writer runs,
#     gold_layer_state defaults to 'stale' instead of being left lying.

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

# Use Hermes venv Python — but verify it actually exists.
PYTHON="/home/ubuntu/.hermes/hermes-agent/venv/bin/python3"
if [ ! -f "${PYTHON}" ]; then
    echo "FATAL: Hermes venv Python not found at ${PYTHON}"
    echo "Run bootstrap_hermes_venv.sh to provision the venv."
    exit 65  # EX_DATAERR
fi

# Verify required Python deps are importable. If not, the entire pipeline
# would otherwise crash silently inside each stage. Better to fail here with
# one clear message than 30 ModuleNotFoundError tracebacks scattered in logs.
if ! "${PYTHON}" -c "import psycopg2, dotenv" 2>/dev/null; then
    echo "FATAL: Hermes venv missing psycopg2 or python-dotenv."
    echo "  ${PYTHON} cannot import psycopg2 / dotenv."
    echo "  Run: bash ${WORKSPACE}/../../bootstrap_hermes_venv.sh"
    exit 70  # EX_SOFTWARE
fi
echo "✅ Hermes venv check: psycopg2 + dotenv importable"

cd "${WORKSPACE}"

# Failure / success tracking arrays
FAILED_BRONZE=()
OK_BRONZE=()
FAILED_SILVER=()
OK_SILVER=()
FAILED_GOLD=()
OK_GOLD=()
FAILED_CONSUMPTION=()
OK_CONSUMPTION=()

# Per-script timeout (seconds)
BRONZE_TIMEOUT=120
SILVER_TIMEOUT=120
GOLD_TIMEOUT=180
CONSUMPTION_TIMEOUT=30

run_bronze() {
    local name="$1"
    local script="$2"
    shift 2
    echo "→ ${name}..."
    if timeout ${BRONZE_TIMEOUT}s "${PYTHON}" "${script}" "$@"; then
        echo "  ✅ ${name} complete"
        OK_BRONZE+=("${name}")
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo "  ⏱️ ${name} TIMEOUT after ${BRONZE_TIMEOUT}s"
        else
            echo "  ⚠️ ${name} FAILED (exit $exit_code)"
        fi
        FAILED_BRONZE+=("${name}")
    fi
}

run_silver() {
    local name="$1"
    local script="$2"
    echo "→ ${name}..."
    if timeout ${SILVER_TIMEOUT}s "${PYTHON}" "${script}"; then
        echo "  ✅ ${name} complete"
        OK_SILVER+=("${name}")
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo "  ⏱️ ${name} TIMEOUT after ${SILVER_TIMEOUT}s"
        else
            echo "  ⚠️ ${name} FAILED (exit $exit_code)"
        fi
        FAILED_SILVER+=("${name}")
    fi
}

run_gold() {
    local name="$1"
    local script="$2"
    echo "→ ${name}..."
    if timeout ${GOLD_TIMEOUT}s "${PYTHON}" "${script}"; then
        echo "  ✅ ${name} complete"
        OK_GOLD+=("${name}")
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo "  ⏱️ ${name} TIMEOUT after ${GOLD_TIMEOUT}s"
        else
            echo "  ⚠️ ${name} FAILED (exit $exit_code)"
        fi
        FAILED_GOLD+=("${name}")
    fi
}

run_consumption() {
    local name="$1"
    local script="$2"
    echo "→ ${name}..."
    if timeout ${CONSUMPTION_TIMEOUT}s "${PYTHON}" "${script}"; then
        echo "  ✅ ${name} complete"
        OK_CONSUMPTION+=("${name}")
    else
        local exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo "  ⏱️ ${name} TIMEOUT after ${CONSUMPTION_TIMEOUT}s"
        else
            echo "  ⚠️ ${name} FAILED (exit $exit_code)"
        fi
        FAILED_CONSUMPTION+=("${name}")
    fi
}

# ════════════════════════════════════════════
echo ""
echo "🔶 BRONZE — Raw Ingestion (by Source System)"
echo "------------------------------------------"

# Binance (crypto) — daily klines
run_bronze "Binance crypto" "shared/scripts/ingest_binance_crypto.py" "1d"

# FMP (equities/fundamentals)
for f in bronze/fmp/*.py; do
    if [ -f "$f" ]; then
        run_bronze "FMP:$(basename "$f" .py)" "$f"
    fi
done

# Interactive Brokers (positions/portfolio + live TWS sync)
# Runs on EC2 gateway directly to avoid IP mismatch with TWS session
echo "Running IBKR ingestion on EC2 gateway..."
ssh -i ~/.ssh/ibkr_ec2.pem -o StrictHostKeyChecking=no -o ConnectTimeout=10 ubuntu@52.74.14.181 '~/run_ibkr_etl.sh' 2>&1 | while read line; do echo "  [EC2] $line"; done
IBKR_EC2_EXIT=${PIPESTATUS[0]}
if [ $IBKR_EC2_EXIT -ne 0 ]; then
    FAILED_BRONZE+=("IBKR:EC2_runner")
    echo "  ⚠️ IBKR EC2 runner failed (exit $IBKR_EC2_EXIT)"
fi

# Keep local IBKR scripts as fallback (disabled - EC2 runner handles all IBKR data)
# for f in bronze/ibkr/*.py; do
#     if [ -f "$f" ]; then
#         run_bronze "IBKR:$(basename "$f" .py)" "$f"
#     fi
# done

# HKEX (Hong Kong equities)
for f in bronze/hkex/*.py; do
    if [ -f "$f" ]; then
        run_bronze "HKEX:$(basename "$f" .py)" "$f"
    fi
done

# Yahoo Finance (equities only — NO CRYPTO)
for f in bronze/yfinance/*.py; do
    if [ -f "$f" ]; then
        run_bronze "YF:$(basename "$f" .py)" "$f"
    fi
done

# FRED (macro indicators)
for f in bronze/fred/*.py; do
    if [ -f "$f" ]; then
        run_bronze "FRED:$(basename "$f" .py)" "$f"
    fi
done

# Manual uploads
for f in bronze/manual/*.py; do
    if [ -f "$f" ]; then
        run_bronze "MANUAL:$(basename "$f" .py)" "$f"
    fi
done

if [ ${#FAILED_BRONZE[@]} -gt 0 ]; then
    echo "⚠️ Bronze failures: ${FAILED_BRONZE[*]}"
fi

echo "✅ Bronze complete (${#FAILED_BRONZE[@]} failures)"

# ════════════════════════════════════════════
echo ""
echo "🔷 SILVER — Clean & Normalize"
echo "------------------------------------------"

# Crypto normalization (from Binance)
run_silver "Crypto normalize" "silver/crypto_normalize.py"

# All silver scripts
for f in silver/*.py; do
    if [ -f "$f" ]; then
        run_silver "$(basename "$f" .py)" "$f"
    fi
done

# IBKR silver promotion (from EC2 bronze data)
run_silver "IBKR promote" "silver/promote_ibkr.py"
run_silver "IBKR orders promote" "silver/promote_ibkr_orders.py"

if [ ${#FAILED_SILVER[@]} -gt 0 ]; then
    echo "⚠️ Silver failures: ${FAILED_SILVER[*]}"
fi

echo "✅ Silver complete (${#FAILED_SILVER[@]} failures)"

# ════════════════════════════════════════════
echo ""
echo "🥇 GOLD — Curate by Asset Type"
echo "------------------------------------------"

# Crypto metrics
run_gold "Crypto KPIs" "gold/crypto/crypto_metrics.py"
run_gold "Crypto metrics build" "gold/crypto/build_crypto_kpis.py"

# All asset types
for asset in equity fx commodity market portfolio ipo strategy; do
    if [ -d "gold/${asset}" ]; then
        for f in gold/${asset}/*.py; do
            if [ -f "$f" ]; then
                run_gold "${asset}:$(basename "$f" .py)" "$f"
            fi
        done
    fi
done

# IBKR gold promotion (from silver data)
run_gold "IBKR promote" "gold/promote_ibkr.py"
run_gold "IBKR orders promote" "gold/promote_ibkr_orders.py"

# S9 MACD signal generation
run_gold "S9 MACD signals" "gold/strategy/s9_macd_daily.py"

if [ ${#FAILED_GOLD[@]} -gt 0 ]; then
    echo "⚠️ Gold failures: ${FAILED_GOLD[*]}"
fi

echo "✅ Gold complete (${#FAILED_GOLD[@]} failures)"

# ════════════════════════════════════════════
echo ""
echo "📊 CONSUMPTION — Serve by Frontend Tab"
echo "------------------------------------------"
for tab in command lab performance portfolio market; do
    if [ -d "consumption/${tab}" ]; then
        for f in consumption/${tab}/*.py; do
            if [ -f "$f" ]; then
                run_consumption "${tab}:$(basename "$f" .py)" "$f"
            fi
        done
    fi
done

if [ ${#FAILED_CONSUMPTION[@]} -gt 0 ]; then
    echo "⚠️ Consumption failures: ${FAILED_CONSUMPTION[*]}"
fi

echo "✅ Consumption complete (${#FAILED_CONSUMPTION[@]} failures)"

# ════════════════════════════════════════════
echo ""
echo "=========================================="

# Write the per-stage truth into .state.json BEFORE sync_gold_layer_state.py runs.
# This is the only place that decides what state to claim — failing fast
# above means we never lie about freshness.
join_csv() { local IFS=','; echo "$*"; }

"${PYTHON}" "${WORKSPACE}/write_pipeline_state.py" \
    --output "${WORKSPACE}/.state.json" \
    --bronze-ok      "$(join_csv "${OK_BRONZE[@]:-}")" \
    --bronze-failed  "$(join_csv "${FAILED_BRONZE[@]:-}")" \
    --silver-ok      "$(join_csv "${OK_SILVER[@]:-}")" \
    --silver-failed  "$(join_csv "${FAILED_SILVER[@]:-}")" \
    --gold-ok        "$(join_csv "${OK_GOLD[@]:-}")" \
    --gold-failed    "$(join_csv "${FAILED_GOLD[@]:-}")" \
    --consumption-ok      "$(join_csv "${OK_CONSUMPTION[@]:-}")" \
    --consumption-failed  "$(join_csv "${FAILED_CONSUMPTION[@]:-}")" \
    && echo "✅ .state.json written" \
    || echo "⚠️ write_pipeline_state.py FAILED — sync will default to 'stale'"

"${PYTHON}" "${WORKSPACE}/sync_gold_layer_state.py" \
    && echo "✅ gold_layer_state synced to DB" \
    || echo "⚠️ sync_gold_layer_state FAILED"

TOTAL_FAILS=$(( ${#FAILED_BRONZE[@]} + ${#FAILED_SILVER[@]} + ${#FAILED_GOLD[@]} + ${#FAILED_CONSUMPTION[@]} ))
echo "DAILY REFRESH COMPLETED: $(date)"
echo "Total failures: ${TOTAL_FAILS} (Bronze:${#FAILED_BRONZE[@]} Silver:${#FAILED_SILVER[@]} Gold:${#FAILED_GOLD[@]} Consumption:${#FAILED_CONSUMPTION[@]})"
echo "Log: ${LOG_FILE}"
echo "=========================================="

# Exit non-zero if any stage failed
exit ${TOTAL_FAILS}
