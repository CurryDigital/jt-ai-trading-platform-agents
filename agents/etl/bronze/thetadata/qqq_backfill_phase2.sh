#!/bin/bash
# QQQ backfill PHASE 2 (kanban t_8d75977e): stability re-pull + downstream.
#
# Why: Phase A chunked pull (03:48-04:32Z) + Phase A2 re-pull (04:32-05:10Z)
# left ~570 dates SHORT (67% — QQQ chains are genuinely narrower than the
# trailing-20 median during regime shifts; same false-positive pattern as the
# SPY 2026-10-06 audit). The 2026-10-07 VERIFIED_THIN amendment accepts a
# SHORT date when two pulls >=4h apart have identical row_count AND
# distinct_contracts. Phase 1's two pulls were <4h apart, so this pass runs
# after the stability clock matures, then re-runs the downstream stages
# (all incremental/idempotent) to pick up the newly credited dates.
#
# Waits for: (a) phase-1 runner completion marker, (b) stability clock
# (no earlier than 09:20 UTC 2026-10-26 = last A2 pull + 4h).
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
set -uo pipefail

ETL_ROOT="/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
PYTHON="/usr/bin/python3"
LOG_DIR="/home/ubuntu/.hermes/profiles/qr_etl/logs/etl"
STATUS_FILE="${LOG_DIR}/qqq_backfill.status"
TS="$(/usr/bin/date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qqq_backfill_phase2_${TS}.log"
CLASSIFY="/home/ubuntu/.hermes/profiles/qr_etl/scripts/deriv_probe_classify.py"
EARLIEST_EPOCH="$(/usr/bin/date -u -d '2026-10-26 09:20:00' +%s)"

exec >>"${LOG_FILE}" 2>&1
mark() { echo "$(/usr/bin/date -u +%FT%TZ) $1" | /usr/bin/tee -a "${STATUS_FILE}"; }

mark "PHASE2_ARMED log=${LOG_FILE}"

# (a) wait for phase 1 completion (poll 60s, cap 6h)
 waited=0
while ! /usr/bin/grep -q 'QQQ_BACKFILL_COMPLETE\|FATAL' "${STATUS_FILE}" 2>/dev/null; do
  /usr/bin/sleep 60; waited=$((waited+60))
  if [ "${waited}" -ge 21600 ]; then mark "PHASE2_FATAL phase1 never completed"; exit 1; fi
done
if /usr/bin/grep -q 'FATAL' "${STATUS_FILE}"; then
  mark "PHASE2_ABORT phase1 FATAL"
  exit 1
fi

# (b) stability clock
now="$(/usr/bin/date -u +%s)"
if [ "${now}" -lt "${EARLIEST_EPOCH}" ]; then
  s=$((EARLIEST_EPOCH - now))
  mark "PHASE2_WAIT stability clock ${s}s"
  /usr/bin/sleep "${s}"
fi

ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
set -a && source "${ENV_FILE}" && set +a
cd "${ETL_ROOT}/bronze/thetadata" || { mark "PHASE2_FATAL cannot cd"; exit 1; }

if ! /usr/bin/curl -sf --max-time 15 \
    "http://127.0.0.1:25503/v3/option/list/expirations?symbol=QQQ" -o /dev/null; then
    mark "PHASE2_FATAL theta terminal down"
    exit 1
fi

mark "PHASE2_PROBE_START stability pass (pull 3, >=4h clock)"
OUT="${LOG_DIR}/.qqq_probe_p2_$$.log"
"${PYTHON}" probe_pull.py --symbol QQQ --windows 2023-06-01:2026-10-23 \
    --endpoints eod,stock --min-dte 7 --max-dte 60 \
    --label QQQ_FREE_FULL_STABILITY2 >"${OUT}" 2>&1
RC=$?
/usr/bin/cat "${OUT}"
if [ "${RC}" -ne 0 ]; then
    SEV="$("${PYTHON}" "${CLASSIFY}" "${OUT}")"
    /usr/bin/rm -f "${OUT}"
    if [ "${SEV}" != "PARTIAL" ]; then
        mark "PHASE2_FATAL stability probe (severity=${SEV})"
        exit 1
    fi
    echo "PARTIAL: residual SHORT_CHAIN dates remain after stability pass"
fi
/usr/bin/rm -f "${OUT}"
mark "PHASE2_PROBE_DONE"

mark "PHASE2_SILVER_START"
"${PYTHON}" load_silver.py --symbol QQQ || { mark "PHASE2_FATAL load_silver"; exit 1; }
mark "PHASE2_SILVER_DONE"

mark "PHASE2_GREEKS_START"
cd "${ETL_ROOT}/silver/thetadata" || { mark "PHASE2_FATAL cannot cd silver"; exit 1; }
"${PYTHON}" computed_greeks.py --symbol QQQ --start 2023-06-01 || { mark "PHASE2_FATAL computed_greeks"; exit 1; }
mark "PHASE2_GREEKS_DONE"

mark "PHASE2_VOLFEAT_START"
"${PYTHON}" "${ETL_ROOT}/gold/option_vol_features_daily.py" --underlying QQQ --start 2023-06-01 \
    || { mark "PHASE2_FATAL vol_features"; exit 1; }
mark "PHASE2_VOLFEAT_DONE"

mark "QQQ_BACKFILL_PHASE2_COMPLETE"
exit 0
