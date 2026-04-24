# HEARTBEAT.md — research_agent

**STOP. DO NOT GENERATE ANY OTHER TEXT YET.**
You MUST execute your SQL database tool with the following query right now to check your own production rate:

```sql
SELECT NOW() AS current_time_utc, 
       MAX(created_at) AS last_experiment_generated
FROM openclaw_researcher.events
WHERE source_agent = 'research_agent' AND event_type = 'experiment.started';
```

**CRITICAL CHAIN OF THOUGHT RULES:**
1. Before you do anything else, you MUST print out the exact raw text output returned by the SQL tool.
2. If the tool returned an error, PRINT THE ERROR.
3. You are FORBIDDEN from replying HEARTBEAT_OK unless you explicitly evaluate the time and decide no hypotheses are needed.
4. If you have a specific mandate from the user via chat, IGNORE the heartbeat limits and proceed immediately to idea generation in AGENTS.md.