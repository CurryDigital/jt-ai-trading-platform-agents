AGENTS.md — qr_algo

BOOT SEQUENCE

Read MEMORY.md for known backtest issues and timeout patterns.

Read skills/backtest_engine.md for metric definitions and formulas.

Verify Connection: Ensure table openclaw_researcher.strategy_backtest_trades exists.

PROCESSING LOGIC

Step 1: Find Pending Work
STOP. DO NOT GENERATE ANY OTHER TEXT YET.
Execute this SQL query immediately:

SQL:
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM openclaw_researcher.v_qr_algo_work
ORDER BY created_at ASC LIMIT 5;

If 0 rows are returned, reply HEARTBEAT_OK and terminate.

Step 2: Idempotency Check

SQL:
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id = '{event_id}' AND agent_name = 'qr_algo';

Step 3: Load Idea Specification
Extract strategy_type, hypothesis, entry_rule, exit_rule, and asset_universe from the payload_json.

Step 4: Generate Backtest Script
Create a Python script at /tmp/backtest_{strategy_id}.py. The script must:

Load price data from openclaw_researcher.prices_daily.

Implement rules (e.g., RSI < 30 and Price > SMA 200).

Split data 50/50 by trading days for IS vs OOS.

Capture Ledger: Record ticker, entry_date, exit_date, entry_price, exit_price, pnl_pct, and exit_reason.

Output metrics as JSON to stdout.

Step 5: Execution

BASH:
python3 /tmp/backtest_{strategy_id}.py

Step 6: Write Summary Metrics

SQL:
UPDATE openclaw_researcher.strategy_workflow
SET metrics = '{metrics_json}', status = 'backtested', updated_at = NOW()
WHERE strategy_id = '{strategy_id}';

Step 6.5: Persist Individual Trades (Evidence Gate)
CRITICAL: Perform a bulk insert of the trade ledger captured in Step 4.

SQL:
INSERT INTO openclaw_researcher.strategy_backtest_trades
(strategy_id, ticker, period_type, entry_date, exit_date, entry_price, exit_price, pnl_pct, holding_days, exit_reason)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);

Step 7: Emit Completion Event

SQL:
INSERT INTO openclaw_researcher.events
(event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('backtest.completed', '{strategy_id}', '{"metrics":{metrics}, "status":"completed"}', 'qr_algo', 'quant');

Step 8: Cleanup

Mark Processed: INSERT INTO openclaw_researcher.event_processing (event_id, agent_name) VALUES ('{event_id}', 'qr_algo');

Remove Files: rm /tmp/backtest_{strategy_id}.py

TECHNICAL GUIDELINES

Annualized Sharpe Formula
Sharpe = (mean_daily_return / std_daily_return) * sqrt(252)

Hard Constraints

Transaction Costs: 0.1% per side (mandatory).

Position Sizing: Equal weight; Max positions = len(universe) / 2.

Drawdown: Must be stored as a negative decimal (e.g., -0.0383 for -3.83%).

Data Integrity: The trade_count in the metrics JSON must match the actual number of rows inserted into strategy_backtest_trades.