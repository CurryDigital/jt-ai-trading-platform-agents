#!/bin/bash
# Hourly Data Refresh Script — Medallion Architecture
# Runs: Bronze → Silver → Gold (no Consumption — daily only)
# Designed for hourly cron execution

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

# Use Hermes venv Python
PYTHON="/home/ubuntu/.hermes/hermes-agent/venv/bin/python3"
if [ ! -f "${PYTHON}" ]; then
    PYTHON="python3"
fi

cd "${WORKSPACE}"

# Failure tracking array
FAILED_BRONZE=()
FAILED_SILVER=()
FAILED_GOLD=()

# Per-script timeout (seconds)
BRONZE_TIMEOUT=20
SILVER_TIMEOUT=15
GOLD_TIMEOUT=15

run_bronze() {
    local name="$1"
    local script="$2"
    shift 2
    echo "→ ${name}..."
    if timeout ${BRONZE_TIMEOUT}s "${PYTHON}" "${script}" "$@"; then
        echo "  ✅ ${name} complete"
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

# ════════════════════════════════════════════
echo ""
echo "🔶 BRONZE — Raw Ingestion (Hourly Sources)"
echo "------------------------------------------"

# Binance (crypto) — hourly klines
run_bronze "Binance crypto" "shared/scripts/ingest_binance_crypto.py" "1h"

# IBKR TWS live sync — positions, account summary (lightweight, can run hourly)
run_bronze "IBKR TWS live" "bronze/ibkr/ingest_ibkr_tws.py"

# FMP — live quotes, lightweight hourly refresh
run_bronze "FMP quotes" "bronze/fmp/ingest_fmp.py"

# NOTE: Yahoo Finance, HKEX, FRED are daily-frequency sources — skipped in hourly
# NOTE: IBKR historical, contracts are daily — skipped in hourly

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

# Asset registry sync
run_silver "Asset registry" "silver/sync_asset_registry.py"

# Market indices sync
run_silver "Market indices" "silver/sync_market_indices.py"

# Prices cleaning (2026-06-22: clean_prices.py deleted as a duplicate of
# clean_unified_prices.py — see the silver-duplicate-resolution commit).
run_silver "clean_unified_prices" "silver/clean_unified_prices.py"

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

# Market metrics
run_gold "Market metrics" "gold/market/build_market_metrics.py"

# FX metrics
run_gold "FX metrics" "gold/fx/build_fx_metrics.py"

# Portfolio snapshot (lightweight, can run hourly for live positions)
run_gold "Portfolio snapshot" "gold/portfolio/build_portfolio_snapshot.py"

if [ ${#FAILED_GOLD[@]} -gt 0 ]; then
    echo "⚠️ Gold failures: ${FAILED_GOLD[*]}"
fi

echo "✅ Gold complete (${#FAILED_GOLD[@]} failures)"

# ════════════════════════════════════════════
echo ""
echo "=========================================="
"${PYTHON}" "${WORKSPACE}/sync_gold_layer_state.py" && echo "✅ gold_layer_state synced to DB" || echo "⚠️ sync_gold_layer_state FAILED"

TOTAL_FAILS=$(( ${#FAILED_BRONZE[@]} + ${#FAILED_SILVER[@]} + ${#FAILED_GOLD[@]} ))
echo "HOURLY REFRESH COMPLETED: $(date)"
echo "Total failures: ${TOTAL_FAILS} (Bronze:${#FAILED_BRONZE[@]} Silver:${#FAILED_SILVER[@]} Gold:${#FAILED_GOLD[@]})"
echo "Log: ${LOG_FILE}"
echo "=========================================="

# Exit non-zero if any stage failed
exit ${TOTAL_FAILS}
