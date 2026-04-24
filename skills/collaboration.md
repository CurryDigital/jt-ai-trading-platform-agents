# Skill: Collaboration

## Purpose
Defines how all OpenClaw agents communicate, hand off 
work, and signal completion. Every agent MUST load and 
follow this skill. There are no direct agent-to-agent 
calls. Everything goes through the event system.

---

## Core Rules

### Rule 1 — Events are the only communication channel
- Agents do not call each other directly.
- To pass work to the next agent: emit an event to the 
 events table.
- To receive work: poll agent_work_queue or your 
 designated view.
- Hub is the only component that sees all events. 
 All others see only their queue.

### Rule 2 — One agent, one decision
Each agent owns exactly one question and emits one 
primary output event:

| Agent | Question | Output event |
|--------------|--------------------------------------|----------------------|
| DE | Is the data ready and clean? | dataset.ready |
| Algo | Does this strategy produce returns? | backtest.completed |
| Risk | Is this strategy safe to promote? | risk.evaluated |
| QA | Does it meet all quality gates? | qa.validated |
| Exp. Manager | What parameters to try next? | experiment.started |
| Monitor | Is any workflow stuck or failing? | workflow.stuck |
| Hub | Which agent handles this event? | (routes, no emission)|

### Rule 3 — Handoff protocol
When your work is complete, in this exact order:
1. Write result to the appropriate table
2. Emit event: domain, type, payload, status=pending
3. Update agent_work_queue row to status=completed
4. Do NOT wait for the next agent to acknowledge

### Rule 4 — Failure handling
- On first failure: retry once
- On second failure: emit workflow.stuck
- Never retry more than twice
- Always update queue row to status=failed before escalating

### Rule 5 — Idempotency
Before starting work:
1. Check event_processing for your (event_id, agent_id)
2. If completed → skip, acknowledge, move on
3. If in_progress → another instance running, do not duplicate
4. If missing → insert it as in_progress, then begin

### Rule 6 — Domain isolation
- Only consume events where domain matches your domain
- Never read or emit cross-domain events
- Hub is the only component that processes all domains

### Rule 7 — Mandatory logging
Write to workflow_events for every action:
- event_type: what triggered this
- agent_id: your identifier
- status: started / completed / failed
- metadata: key decision summary only

### Rule 8 — Pipeline subagent context
DE, Algo, Risk, and QA share experiment_id as a context 
key. Every event payload in a pipeline run MUST include 
experiment_id.

---

## Base Event Payload Standard

{
 "id": "uuid",
 "domain": "quant",
 "type": "event.type",
 "experiment_id": "uuid",
 "strategy_id": "uuid or null",
 "payload": { ... },
 "status": "pending",
 "created_at": "iso8601"
}
---

---

## Skills Loading Table

Each agent session system prompt must load exactly the skills it needs.
Loading unnecessary skills wastes context. Missing a skill causes behaviour gaps.

| Agent | Required skills |
|-------|----------------|
| Hub | collaboration.md |
| Monitor | collaboration.md, self_healing.md, observability.md |
| DE | collaboration.md, data_quality.md, etl_contracts.md, observability.md |
| Algo | collaboration.md, backtest_engine.md, observability.md |
| Risk | collaboration.md, risk_framework.md, observability.md |
| QA | collaboration.md, risk_framework.md, lineage_and_promotion.md, observability.md |
| Exp. Manager | collaboration.md, experiment_design.md, lineage_and_promotion.md, observability.md |
| Idea Intake | collaboration.md, idea_parsing.md, observability.md |

To load a skill in an OpenClaw session system prompt:
  {{file: skills/collaboration.md}}
  {{file: skills/data_quality.md}}
