# Skill: Data Quality

## Purpose
Defines the five mandatory quality checks every dataset must pass
before the DE agent emits dataset.ready. Any failure blocks the
pipeline. Two checks are currently live; three are stubs pending
full market data connection.

Load this skill: DE agent only.

---

## The Five Gates (run in order, stop at first fail)

### Gate 1 — No missing bars (LIVE)
Source: `gold.stock_metrics_history`

For each ticker in asset_universe:
- Count available trading days between date_range.start and date_range.end
- Expected trading days ≈ (calendar days × 0.714) — accounts for weekends
- FAIL if available < expected × 0.95 (allows 5% tolerance for holidays)
- Log: "Check 1 FAIL — AAPL: 187 days available, expected ~198"
- Log: "Check 1 PASS — all tickers ≥ 95% coverage"

### Gate 2 — No lookahead bias (STUB → implement when feature pipeline connected)
Verify that no feature column uses data from T+1 or later.
Until connected: log "Check 2 stub — skipping lookahead check" and PASS.

Implementation target:
- For each feature column, assert max(feature_date) <= price_date for same row
- Flag columns where any row violates this

### Gate 3 — Dataset version matches param_set (LIVE)
The dataset_id written to strategy_workflow must correspond to the
exact date_range and asset_universe requested in the experiment param_set.
- FAIL if date_range.start or date_range.end drift by more than 1 calendar day
- FAIL if asset_universe has any ticker missing entirely from the dataset
- Log specific missing tickers by name

### Gate 4 — No price spikes > 5 std devs (STUB → implement when market_data table connected)
Until connected: log "Check 4 stub — skipping spike check" and PASS.

Implementation target:
```sql
SELECT ticker, date, close,
       AVG(close) OVER w AS mean,
       STDDEV(close) OVER w AS stddev,
       ABS(close - AVG(close) OVER w) / NULLIF(STDDEV(close) OVER w, 0) AS z_score
FROM gold.stock_metrics_history
WHERE ticker = ANY(%s) AND date BETWEEN %s AND %s
WINDOW w AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW)
HAVING z_score > 5
```
FAIL if any rows returned. Log: "Check 4 FAIL — TSLA 2022-08-05 z=7.3"

### Gate 5 — History ≥ 2× lookback_window before start date (LIVE)
Source: `gold.stock_metrics_history`

For each ticker:
- Count rows where date < date_range.start
- Required: count ≥ param_set.lookback_window × 2
- FAIL if any ticker falls short
- Log: "Check 5 FAIL — NVDA: only 12 rows pre-start, need 40 (lookback 20)"

---

## Failure behaviour

- On any gate failure: emit workflow.stuck, do NOT emit dataset.ready
- Retry logic: DE agent retries once automatically (Rule 4 from collaboration.md)
- After 2 failures: mark event as failed, surface to Monitor

## Quality flags payload

When emitting dataset.ready, include quality_flags array:
```json
{
  "quality_flags": [],           // empty = all 5 passed
  "quality_flags": ["missing_bars", "insufficient_history"]  // partial passes
}
```

Downstream agents (Algo) must check quality_flags and may reject
datasets with flags even if DE decided to pass them through.

---

## Stub completion checklist

When connecting stubs to live data, update this file:
- [ ] Gate 2: lookahead bias — connect to feature pipeline
- [ ] Gate 4: price spikes — connect to market_data table
