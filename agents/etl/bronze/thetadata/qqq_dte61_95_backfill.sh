#!/bin/bash
# QQQ ThetaData DTE 61-95 supplemental backfill (kanban t_03a02247, Track B
# deriv_qqq_trend_callspread_v1 60-90 DTE leg coverage). Free-tier probe
# 2026-10-27 confirmed availability (QQQ 286-1054 rows/date in band,
# chains to DTE ~980; SPY 1114-1128).
#
# Deliberate deviations from the primary 7-60 pipeline:
#   --no-gate: completeness baseline reads silver.thetadata_date_completeness
#     keyed (symbol, endpoint, trade_date) — a 61-95-only chain (~300-1100
#     rows) vs the 7-60 baseline (~2600 rows) would mass-record SHORT and
#     overwrite the primary band's VERIFIED verdicts + poison the nightly
#     baseline. Gate semantics don't apply to a partial-band pull.
#   --skip-same-label-only: resume credit only from SUCCESS runs labelled
#     QQQ_DTE61_95, independent of the primary band's credit set.
# Coverage is instead verified post-hoc by row counts per date in bronze.
#
# Phases: A probe_pull chunks -> B load_silver (incremental) ->
# C computed_greeks -> D vol features. Idempotent; safe to re-run.
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
set -uo pipefail

ETL_ROOT="/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
PYTHON="/usr/bin/python3"
LOG_DIR="/home/ubuntu/.hermes/profiles/qr_etl/logs/etl"
TS="$(/usr/bin/date +%Y%m%d_%H%M%S)"
LOG_FILE="${LOG_DIR}/qqq_dte61_95_${TS}.log"
STATUS_FILE="${LOG_DIR}/qqq_dte61_95.status"
/usr/bin/mkdir -p "${LOG_DIR}"

exec >>"${LOG_FILE}" 2>&1

mark() { echo "$(/usr/bin/date -u +%FT%TZ) $1" | /usr/bin/tee -a "${STATUS_FILE}"; }

echo "=========================================="
echo "QQQ DTE61-95 BACKFILL STARTED: $(/usr/bin/date -u) UTC"
echo "=========================================="
ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
set -a && source "${ENV_FILE}" && set +a

cd "${ETL_ROOT}/bronze/thetadata" || { mark "FATAL cannot cd"; exit 1; }

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

mark "PHASE_A_START chunks=${#CHUNKS[@]}"
for WIN in "${CHUNKS[@]}"; do
  mark "CHUNK_START ${WIN}"
  if ! "${PYTHON}" probe_pull.py --symbol QQQ --windows "${WIN}" \
      --endpoints eod --min-dte 61 --max-dte 95 \
      --label QQQ_DTE61_95 --no-gate --skip-same-label-only; then
      mark "FATAL chunk ${WIN}"
      exit 1
  fi
  mark "CHUNK_DONE ${WIN}"
done

mark "PHASE_B_START load_silver incremental"
"${PYTHON}" load_silver.py --symbol QQQ || { mark "FATAL load_silver"; exit 1; }
mark "PHASE_B_DONE"

mark "PHASE_C_START computed_greeks"
cd "${ETL_ROOT}/silver/thetadata" || { mark "FATAL cannot cd silver"; exit 1; }
"${PYTHON}" computed_greeks.py --symbol QQQ --start 2023-06-01 \
    || { mark "FATAL computed_greeks"; exit 1; }
mark "PHASE_C_DONE"

mark "PHASE_D_START vol_features"
"${PYTHON}" "${ETL_ROOT}/gold/option_vol_features_daily.py" --underlying QQQ --start 2023-06-01 \
    || { mark "FATAL vol_features"; exit 1; }
mark "PHASE_D_DONE"

mark "QQQ_DTE61_95_BACKFILL_COMPLETE"
echo "QQQ DTE61-95 BACKFILL COMPLETED: $(/usr/bin/date -u) UTC"
exit 0
