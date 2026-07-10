#!/usr/bin/env bash
set -euo pipefail

ENV_FILE="/home/ubuntu/.hermes/profiles/qr_etl/env/etl.env"
if [ -f "${ENV_FILE}" ]; then
  set -a && source "${ENV_FILE}" && set +a
fi

export PGHOST="${DB_HOST:-}"
export PGDATABASE="${DB_NAME:-}"
export PGUSER="${DB_USER:-}"
export PGPASSWORD="${DB_PASSWORD:-}"

fail=0

check() {
  local label="$1" expected="$2" actual="$3"
  if [[ "$actual" == "$expected" ]]; then
    echo "PASS: $label ($actual)"
  else
    echo "FAIL: $label expected=$expected actual=$actual"
    fail=1
  fi
}

run_sql() {
  psql -h "${PGHOST}" -d "${PGDATABASE}" -U "${PGUSER}" -t -c "$1" | xargs
}

run_sql_raw() {
  psql -h "${PGHOST}" -d "${PGDATABASE}" -U "${PGUSER}" -t -c "$1"
}

echo "--- Verifying ETF Multi-Asset PAPER live signal ---"

mode=$(run_sql "SELECT execution_mode FROM gold.strategy_registry WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation';")
check "registry execution_mode" "PAPER" "$mode"

status=$(run_sql "SELECT status FROM gold.strategy_registry WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation';")
check "registry status" "paper" "$status"

universe=$(run_sql "SELECT array_length(universe_tickers, 1) FROM gold.strategy_registry WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation';")
check "registry universe size" "3" "$universe"

capital=$(run_sql "SELECT in_market_capital FROM gold.strategy_registry WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation';")
check "registry in_market_capital" "10000.00" "$capital"

se_count=$(run_sql "SELECT COUNT(*) FROM gold.signal_evaluations WHERE family_key='tactical' AND ticker IN ('IWM','VTEB','VTI');")
check "signal_evaluations live ticker rows" "3" "$se_count"

se_direction=$(run_sql "SELECT COUNT(DISTINCT direction) FROM gold.signal_evaluations WHERE family_key='tactical' AND ticker IN ('IWM','VTEB','VTI');")
check "signal_evaluations distinct directions" "1" "$se_direction"

se_buy=$(run_sql "SELECT COUNT(*) FROM gold.signal_evaluations WHERE family_key='tactical' AND ticker IN ('IWM','VTEB','VTI') AND direction='BUY';")
check "signal_evaluations BUY rows" "3" "$se_buy"

sts_count=$(run_sql "SELECT COUNT(*) FROM gold.strategy_ticker_scores WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation';")
check "strategy_ticker_scores rows" "3" "$sts_count"

sts_paper=$(run_sql "SELECT COUNT(*) FROM gold.strategy_ticker_scores WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation' AND criteria_met->>'execution_mode'='PAPER';")
check "strategy_ticker_scores PAPER criteria" "3" "$sts_paper"

weight_sum=$(run_sql "SELECT ROUND(SUM((criteria_met->>'weight')::numeric)::numeric, 6) FROM gold.strategy_ticker_scores WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation';")
if (( $(echo "$weight_sum == 1" | bc -l) )); then
  echo "PASS: weight sum ~= 1 ($weight_sum)"
else
  echo "FAIL: weight sum expected=1 actual=$weight_sum"
  fail=1
fi

max_weight=$(run_sql "SELECT MAX((criteria_met->>'weight')::numeric) FROM gold.strategy_ticker_scores WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation';")
if (( $(echo "$max_weight <= 0.70" | bc -l) )); then
  echo "PASS: max weight <= 0.70 ($max_weight)"
else
  echo "FAIL: max weight > 0.70 ($max_weight)"
  fail=1
fi

# Verify each live ticker weight is present
for ticker in IWM VTEB VTI; do
  expected_weight=$({
    case "$ticker" in
      IWM)  echo 0.1409 ;;
      VTEB) echo 0.6567 ;;
      VTI)  echo 0.2024 ;;
    esac
  })
  actual_weight=$(run_sql "SELECT (criteria_met->>'weight')::numeric FROM gold.strategy_ticker_scores WHERE strategy_id='ETF_Multi_Asset_Tactical_Allocation' AND ticker='$ticker';")
  diff=$(echo "$actual_weight - $expected_weight" | bc -l | tr -d '-')
  if (( $(echo "$diff < 0.0001" | bc -l) )); then
    echo "PASS: $ticker weight ~$expected_weight ($actual_weight)"
  else
    echo "FAIL: $ticker weight expected=$expected_weight actual=$actual_weight"
    fail=1
  fi
done

# Latest paper run should reflect the 3 live positions
prl_positions=$(run_sql "SELECT num_positions FROM gold.paper_run_log WHERE run_date=CURRENT_DATE AND status='ok' ORDER BY created_at DESC LIMIT 1;")
if [[ -n "$prl_positions" ]]; then
  check "paper_run_log latest ok positions" "3" "$prl_positions"
else
  echo "FAIL: no ok paper_run_log row for today"
  fail=1
fi

sig_active=$(run_sql "SELECT active FROM gold.strategy_signals WHERE strategy_id=21 ORDER BY date DESC LIMIT 1;")
check "strategy_signals active" "t" "$sig_active"

if [[ $fail -eq 0 ]]; then
  echo "ALL CHECKS PASSED"
else
  echo "SOME CHECKS FAILED"
  exit 1
fi
