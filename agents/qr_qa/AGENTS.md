BOOT SEQUENCE

Read MEMORY.md for gate failure patterns.

Read skills/lineage_and_promotion.md for promotion rules.

Verify Access: openclaw_researcher.strategy_backtest_trades.

PROCESSING LOGIC

Step 1: Find Pending Work
STOP. DO NOT GENERATE ANY OTHER TEXT YET.
Execute this SQL query immediately:

SQL:
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM openclaw_researcher.v_qr_qa_work
ORDER BY created_at ASC LIMIT 5;

Step 2: Idempotency Check

SQL:
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = '{event_id}' AND agent_name = 'qr_qa';

Step 3: Load Context and Evidence
Extract conviction_score and risk_score from the debate payload.

SQL:
SELECT metrics, risk_score, risk_approved, conviction_score
FROM openclaw_researcher.strategy_workflow WHERE strategy_id = '{strategy_id}';

NEW: Load Trade Evidence
SQL:
SELECT COUNT(*) as actual_trade_count, SUM(pnl_pct) as total_raw_pnl
FROM openclaw_researcher.strategy_backtest_trades
WHERE strategy_id = '{strategy_id}';

Step 4: Run 7 Gates in Strict Order

Gate 0 — Data Integrity (ANTI-HALLUCINATION):
Check if (metrics->trade_count_is + metrics->trade_count_oos) == actual_trade_count.
If MISMATCH → REJECT: "Hallucination Detected. Summary count {metrics_count} does not match database record {actual_count}."

Gate 1 — Risk Clearance:
risk_approved must be true.

Gate 2 — Sharpe OOS:
Check sharpe_oos against qa_min_sharpe_oos threshold.

Gate 3 — Max Drawdown:
Check |max_drawdown| against qa_max_drawdown.

Gate 4 — Trade Count:
Check trade_count_oos against qa_min_trade_count_oos.

Gate 5 — IS/OOS Ratio:
Check sharpe_ratio_is_oos against qa_min_sharpe_ratio_is_oos.

Gate 6 — Conviction:
Check conviction_score against qa_min_conviction_score.

Step 5: Handle Result

ON PASS:
Execute promotion transaction (Lineage + Event).

ON FAIL:
Emit rejection event. Include which gate failed (0 through 6).

Step 6: Mark Processed
SQL:
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name) VALUES ('{event_id}', 'qr_qa');