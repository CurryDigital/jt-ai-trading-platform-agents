#!/bin/bash
# QQQ ThetaData free-window chunked backfill (kanban t_8d75977e, Track B
# deriv_qqq_trend_callspread_v1 dependency). Mirrors the SPY pipeline:
# bronze probe_pull (eod,stock; 7-60 DTE) -> silver load --full ->
# COMPUTED greeks -> gold vol features.
#
# Chunked into ~6-month windows: a single multi-year probe_pull dies around
# day ~190 in completeness_baseline (statement-level kill as the trailing-20
# median CTE grows); fresh process per chunk avoids it. Resume semantics:
# SUCCESS-credited dates are skipped, so this script is idempotent — safe to
# re-run after an interruption.
#
# Phases:
#   A  probe_pull per chunk (PARTIAL/SHORT_CHAIN tolerated; FATAL aborts)
#   A2 stability re-pull over the full window (refetches SHORT-held dates
#      only; >=4h stability clock satisfied by elapsed chunk time)
#   B  load_silver.py --symbol QQQ --full (reconciliation gate)
#   C  computed_greeks.py --symbol QQQ --start 2023-06-01 (CRR N=200 American,
#      escrowed divs from deriv.underlying_dividends, DTB3)
#   D  option_vol_features_daily.py --underlying QQQ --start 2023-06-01
#
# Status markers appended to $STATUS_FILE; full log in $LOG_FILE.
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
set -uo pipefail

ETL_ROOT="/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
PYTHON="/usr/bin/python3"
LOG_DIR="/home/ubuntu/.hermes/profiles/qr_etl/logs/etl"
TS="$(/usr/bin/date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qqq_backfill_${TS}.log"
STATUS_FILE="${LOG_DIR}/qqq_backfill.status"
CLASSIFY="/home/ubuntu/.hermes/profiles/qr_etl/scripts/deriv_probe_classify.py"
/usr/bin/mkdir -p "${LOG_DIR}"

exec >>"${LOG_FILE}" 2>&1

mark() { echo "$(/usr/bin/date -u +%FT%TZ) $1" | /usr/bin/tee -a "${STATUS_FILE}"; }

echo "=========================================="
echo "QQQ BACKFILL STARTED: $(/usr/bin/date -u) UTC"
echo "=========================================="
ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
set -a && source "${ENV_FILE}" && set +a

cd "${ETL_ROOT}/bronze/thetadata" || { mark "FATAL cannot cd"; exit 1; }

# Theta Terminal health check
if ! /usr/bin/curl -sf --max-time 15 \
    "http://127.0.0.1:25503/v3/option/list/expirations?symbol=QQQ" -o /dev/null; then
    mark "FATAL theta terminal down"
    exit 1
fi

CHUNKS=(
  "2023-06-01:2023-11-30"
  "2023-12-01:2024-05-31"
  "2024-06-01:2024-11-30"
  "2024-12-01:2025-05-31"
  "2025-06-01:2025-11-30"
  "2025-12-01:2026-05-31"
  "2026-06-01:2026-10-23"
)

run_probe() {  # $1=window  $2=label  -> 0 ok/partial, 1 fatal
  local WIN="$1" LABEL="$2"
  local OUT="${LOG_DIR}/.qqq_probe_$$.log"
  "${PYTHON}" probe_pull.py --symbol QQQ --windows "${WIN}" \
      --endpoints eod,stock --min-dte 7 --max-dte 60 \
      --label "${LABEL}" >"${OUT}" 2>&1
  local RC=$?
  /usr/bin/cat "${OUT}"
  if [ "${RC}" -ne 0 ]; then
      local SEV
      SEV="$("${PYTHON}" "${CLASSIFY}" "${OUT}")"
      /usr/bin/rm -f "${OUT}"
      if [ "${SEV}" = "PARTIAL" ]; then
          echo "PARTIAL ${WIN}: SHORT_CHAIN-only; continuing"
          return 0
      fi
      echo "FATAL ${WIN}: probe_pull failed (severity=${SEV})"
      return 1
  fi
  /usr/bin/rm -f "${OUT}"
  return 0
}

mark "PHASE_A_START chunks=${#CHUNKS[@]}"
for WIN in "${CHUNKS[@]}"; do
  mark "CHUNK_START ${WIN}"
  if ! run_probe "${WIN}" QQQ_FREE_FULL; then
      mark "FATAL chunk ${WIN}"
      exit 1
  fi
  mark "CHUNK_DONE ${WIN}"
done

mark "PHASE_A2_START stability re-pull full window"
if ! run_probe "2023-06-01:2026-10-23" QQQ_FREE_FULL_STABILITY; then
    mark "FATAL stability re-pull"
    exit 1
fi
mark "PHASE_A2_DONE"

mark "PHASE_B_START load_silver --full"
"${PYTHON}" load_silver.py --symbol QQQ --full || { mark "FATAL load_silver"; exit 1; }
mark "PHASE_B_DONE"

mark "PHASE_C_START computed_greeks"
cd "${ETL_ROOT}/silver/thetadata" || { mark "FATAL cannot cd silver"; exit 1; }
"${PYTHON}" computed_greeks.py --symbol QQQ --start 2023-06-01 || { mark "FATAL computed_greeks"; exit 1; }
mark "PHASE_C_DONE"

mark "PHASE_D_START vol_features"
"${PYTHON}" "${ETL_ROOT}/gold/option_vol_features_daily.py" --underlying QQQ --start 2023-06-01 \
    || { mark "FATAL vol_features"; exit 1; }
mark "PHASE_D_DONE"

mark "QQQ_BACKFILL_COMPLETE"
echo "QQQ BACKFILL COMPLETED: $(/usr/bin/date -u) UTC"
exit 0
