AGENTS.md — qr_risk (Evidence-Based Edition)

BOOT SEQUENCE

Read MEMORY.md for threshold tuning history.

Read skills/risk_framework.md for evaluation methodology.

Verify Access: openclaw_researcher.strategy_backtest_trades.

PROCESSING LOGIC

Step 1: Find Pending Work
STOP. DO NOT GENERATE ANY OTHER TEXT YET.
Execute this SQL query immediately:

SQL:
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM openclaw_researcher.v_qr_risk_work
ORDER BY created_at ASC LIMIT 5;

If 0 rows are returned, reply HEARTBEAT_OK and terminate.

Step 2: Idempotency Check

SQL:
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = '{event_id}' AND agent_name = 'qr_risk';

Step 3: Load Metrics and Trade Evidence
Extract the metrics object from the event payload.

SQL:
SELECT metrics FROM openclaw_researcher.strategy_workflow
WHERE strategy_id = '{strategy_id}';

NEW: Load Ticker-Level Concentration Evidence
SQL:
SELECT ticker, COUNT() as trade_count, (COUNT()::float / SUM(COUNT(*)) OVER()) as exposure_pct
FROM openclaw_researcher.strategy_backtest_trades
WHERE strategy_id = '{strategy_id}'
GROUP BY ticker
ORDER BY exposure_pct DESC LIMIT 1;

Step 4: Load Thresholds from risk_config

SQL:
SELECT name, operator, value, description
FROM openclaw_researcher.risk_config
WHERE enabled = true AND name NOT LIKE 'qa_%'
ORDER BY name;

Step 5: Evaluate 6 Risk Checks

Check 1: high_drawdown (Metric: max_drawdown)
Check 2: low_sharpe_oos (Metric: sharpe_oos)

Check 3: concentration_risk (NEW EVIDENCE SOURCE)
Use the exposure_pct calculated from strategy_backtest_trades in Step 3.
Flag if: exposure_pct > threshold (concentration_risk).

Check 4: overfitting_signal (Metric: sharpe_ratio_is_oos)
Check 5: low_trade_count (Metric: trade_count_oos)
Check 6: tail_risk (Metric: cvar)

Compute risk_score = (count of flags) / 6.
risk_approved = true if risk_score is 0.0, else false.

Step 6: Write to strategy_workflow

SQL:
UPDATE openclaw_researcher.strategy_workflow
SET risk_score = {score}, risk_flags = '{flags_json}', risk_approved = {approved}, risk_notes = '{notes}', risk_evaluated_at = NOW()
WHERE strategy_id = '{strategy_id}';

Step 7: Emit risk.evaluated (ALWAYS)

SQL:
INSERT INTO openclaw_researcher.events
(event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('risk.evaluated', '{strategy_id}', '{"risk_score":{score},"risk_approved":{approved},"risk_flags":{flags}}', 'qr_risk', 'quant');

Step 8: Mark Processed

SQL:
INSERT INTO openclaw_researcher.event_processing
(event_id, agent_name) VALUES ('{event_id}', 'qr_risk')
ON CONFLICT DO NOTHING;

LEARNING TRIGGERS

Track which tickers trigger concentration_risk most often.

If a strategy passes risk but fails the QA "Data Integrity" gate, flag for threshold tightening.