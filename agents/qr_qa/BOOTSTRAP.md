# BOOTSTRAP.md - qr_qa First Run

QA is stateless. No operator conversation. No persistent state.
Bootstrap is purely a readiness check.

## Step 1 — Confirm workspace files
- [ ] `IDENTITY.md` — present
- [ ] `SOUL.md` — present
- [ ] `TOOLS.md` — present, gate table confirmed against `event_contracts.md`
- [ ] `HEARTBEAT.md` — present and empty (QA does not heartbeat)
- [ ] `MEMORY.md` — create empty if missing

## Step 2 — Confirm DB connectivity and access
- [ ] `SELECT 1` — RDS reachable
- [ ] `SELECT * FROM risk_config WHERE key LIKE 'qa_%'` — confirm all 4 QA threshold rows exist
- [ ] `SELECT 1 FROM v_qa_work LIMIT 1` — view accessible (can be empty)
- [ ] `SELECT 1 FROM v_pending_strategies LIMIT 1` — view accessible
- [ ] `SELECT 1 FROM event_processing LIMIT 1` — idempotency table accessible
- [ ] `SELECT 1 FROM strategy_lineage LIMIT 1` — lineage table accessible and writable

## Step 3 — Confirm atomic write pattern
Read `skills/lineage_and_promotion.md`. Confirm `_write_lineage_and_emit()` uses a single `conn.commit()` wrapping both INSERTs.

## Step 4 — Confirm threshold values
Run: `SELECT key, value FROM risk_config WHERE key LIKE 'qa_%'`
Log the results. Confirm they match the expected defaults:
- `qa_min_sharpe_oos`: 0.60
- `qa_max_drawdown`: 0.20
- `qa_min_trade_count_oos`: 30
- `qa_min_sharpe_ratio_is_oos`: 0.75

If any row is missing: log CRITICAL and halt. QA must not run with incomplete thresholds.

## Step 5 — Done
Delete this file. QA will process events as they arrive.