# HEARTBEAT.md — qr_idea_intake (every 5 min)

```
schedule: */5 * * * *
target:   agent:qr_idea_intake:main
message:  Notification cycle. Find the next un-relayed event of interest, format per AGENTS.md, deliver to operator over Telegram, mark processed.
```

## What "the next un-relayed event of interest" means

Run exactly this query (cast both sides of the join to text — `events.id` is uuid, `event_processing.event_id` is uuid; native equality works on the live schema, but we cast for fork-safety):

```sql
SELECT e.id, e.event_type, e.strategy_id, e.payload_json, e.created_at
FROM   openclaw_researcher.events e
LEFT JOIN openclaw_researcher.event_processing ep
       ON ep.event_id = e.id AND ep.agent_name = 'qr_idea_intake'
WHERE  e.event_type IN ('qa.validated','workflow.stuck','etl.partial','etl.failed','etl.operator_alert')
  AND  e.domain = 'quant'
  AND  ep.event_id IS NULL
ORDER  BY e.created_at ASC
LIMIT  1;
```

## Branches

- **0 rows returned** → emit `HEARTBEAT_OK` to log and exit.
- **1 row returned**:
  1. Format per `AGENTS.md` alert table.
  2. Deliver via Telegram bot.
  3. `INSERT INTO event_processing (event_id, agent_name) VALUES (:id, 'qr_idea_intake') ON CONFLICT DO NOTHING;`
  4. Exit. The next heartbeat will pick up the next event — do not loop in one wake.

## Failure recovery

If Telegram delivery fails, **do not** mark processed. The next heartbeat retries.
After 3 consecutive failures on the same event, emit `workflow.stuck` with reason `telegram_unreachable` so qr_monitor escalates.
