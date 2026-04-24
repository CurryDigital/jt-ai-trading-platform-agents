AGENTS.md — qr_debate

BOOT SEQUENCE

Read MEMORY.md for debate calibration notes.

Read skills/debate_framework.md for argument patterns.

CRITICAL ARCHITECTURAL CONSTRAINTS:

FORBIDDEN TOOL: You are strictly forbidden from using the Sub-agent tool. Process items sequentially.

POSTGRES TYPING: Whenever comparing event IDs, explicitly cast them to text to avoid UUID errors (e.g., event_id::text = '{event_id}').

BATCH LIMIT: Process a maximum of 5 strategies per run.

PROCESSING LOGIC

Step 1: Find pending work
STOP. DO NOT GENERATE ANY OTHER TEXT YET.
Execute this SQL query immediately via your tool:

SQL:
SELECT event_id, event_type, strategy_id, payload_json, created_at
FROM openclaw_researcher.v_qr_debate_work
ORDER BY created_at ASC LIMIT 5;

CRITICAL CHAIN OF THOUGHT RULES:

Print out the exact raw JSON or text output returned by the SQL tool.

If the tool returned an error, PRINT THE ERROR.

If 0 rows are returned, print HEARTBEAT_OK and terminate.

If a row is returned, process each one sequentially using the steps below.

Step 2: Idempotency Check
SQL:
SELECT 1 FROM openclaw_researcher.event_processing
WHERE event_id::text = '{event_id}' AND agent_name = 'qr_debate';

If exists → skip this event and move to the next.

Step 3: Load Context
Load from strategy_workflow:
SQL:
SELECT metrics, risk_score, risk_flags, risk_approved, risk_notes, experiment_id, strategy_id
FROM openclaw_researcher.strategy_workflow WHERE strategy_id::text = '{strategy_id}';

Load original hypothesis:
SQL:
SELECT payload_json FROM openclaw_researcher.events
WHERE strategy_id::text = '{strategy_id}' AND event_type = 'experiment.started'
ORDER BY created_at DESC LIMIT 1;

Step 4: The "Fail-Fast" Gate (CRITICAL)
Evaluate the risk_approved flag from Step 3:

IF risk_approved is FALSE: Do not write a debate. Set conviction_score = 0.0, set bull_summary to "None", set bear_summary to "Auto-rejected due to Risk Failure: [insert risk_notes]". Skip Steps 5, 6, and 7. Proceed directly to Step 8.

IF risk_approved is TRUE: Proceed to Step 5.

Step 5: Bull Case (Round 1)
Argue FOR this strategy (Write 3 bullet points):

Do the backtest metrics support the hypothesis?

Are there historical analogues where similar signals worked?

What upside isn't captured in the numbers?

Step 6: Bear Case (Round 2)
Argue AGAINST this strategy (Write 3 bullet points):

IS/OOS Sharpe divergence — overfitting risk?

Would this fail in a different regime (bull→bear)?

What's the worst-case drawdown scenario?

Step 7: Synthesis — Conviction Score
Produce a score from 0.0 to 1.0 based on your debate:

0.8-1.0: Strong conviction (Proceed)

0.5-0.7: Moderate (Proceed with awareness)

0.0-0.4: Weak (Reject)

Step 8: Write Results and Emit
Update strategy_workflow:
SQL:
UPDATE openclaw_researcher.strategy_workflow
SET conviction_score = {score}, debate_summary = '{bull_summary} | {bear_summary}'
WHERE strategy_id::text = '{strategy_id}';

Emit debate.completed:
SQL:
INSERT INTO openclaw_researcher.events
(event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('debate.completed', '{strategy_id}',
'{{"experiment_id":"{exp_id}","strategy_id":"{strategy_id}", "conviction_score":{score},"bull_points":[...],"bear_points":[...], "risk_approved":{from_risk},"risk_score":{from_risk}}}',
'qr_debate', 'quant');

Mark processed:
SQL:
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
VALUES ('{event_id}', 'qr_debate') ON CONFLICT DO NOTHING;