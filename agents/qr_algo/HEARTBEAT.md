# HEARTBEAT.md — qr_algo

**STOP. DO NOT GENERATE ANY OTHER TEXT YET.**
You MUST execute your SQL database tool with the following query right now:

```sql
SELECT event_id, event_type, strategy_id, payload_json, created_at 
FROM openclaw_researcher.v_qr_algo_work 
ORDER BY created_at ASC LIMIT 5;
```

**CRITICAL CHAIN OF THOUGHT RULES:**
1. Before you do anything else, you MUST print out the exact raw JSON or text output returned by the SQL tool.
2. If the tool returned an error, PRINT THE ERROR.
3. You are FORBIDDEN from replying HEARTBEAT_OK unless you have explicitly printed "TOOL RETURNED 0 ROWS" first. 
4. If a row is returned, proceed to the steps in AGENTS.md.