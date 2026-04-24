# Hub Event Router

Event-driven multi-agent architecture for quant research. Replaces polling/heartbeat patterns with a reactive event bus.

## Overview

```
┌─────────────┐     emit event      ┌─────────────┐     route      ┌─────────────┐
│   Agent A   │ ──────────────────► │  Hub Router │ ─────────────► │   Agent B   │
│  (source)   │                     │   (router)  │  (via agentToAgent)
└─────────────┘                     └──────┬──────┘                └─────────────┘
                                           │
                                           ▼
                                    ┌─────────────┐
                                    │  PostgreSQL │
                                    │  events DB  │
                                    └─────────────┘
```

## Architecture Principles

1. **Database is source of truth** - All events persisted to PostgreSQL
2. **Agents don't poll** - Only execute when triggered by event
3. **Every action emits an event** - Full audit trail
4. **Hub routes events** - Deterministic routing rules
5. **Agents are stateless** - Receive, work, emit, exit

## Quick Start

### 1. Initialize Database

```bash
# Set database URL
export HUB_DATABASE_URL="postgresql://user:pass@localhost:5432/hub_events"

# Run schema
psql $HUB_DATABASE_URL -f hub/schema.sql
```

### 2. Emit an Event

```python
from hub import emit_event

emit_event(
    event_type="backtest.completed",
    strategy_id="104",
    payload={"sharpe": 1.42, "drawdown": -0.08, "trades": 213},
    source_agent="algo"
)
# Hub automatically routes to QA agent
```

### 3. Build an Agent

```python
from hub.sdk import Agent, Event

class AlgoAgent(Agent):
    def __init__(self):
        super().__init__("algo")
    
    def on_event(self, event: Event):
        if event.event_type == "dataset.ready":
            # Run backtest
            result = run_backtest(event)
            
            # Record lineage for reproducibility
            self.lineage.record(
                strategy_id=event.strategy_id,
                dataset_version="equities_daily_v3",
                backtest_engine_version="engine_v2.1",
                strategy_parameters={"lookback": 20},
                result_metrics=result,
                source_event_id=event.id
            )
            
            # Emit completion
            self.emit_event(
                event_type="backtest.completed",
                strategy_id=event.strategy_id,
                payload=result
            )

agent = AlgoAgent()
agent.run()  # Processes pending events and exits
```

## Database Schema

### events
Stores all system events - the event log.

```sql
id UUID PRIMARY KEY
event_type TEXT NOT NULL
strategy_id TEXT
payload_json JSONB NOT NULL
source_agent TEXT NOT NULL
created_at TIMESTAMP
```

### event_processing
Tracks which agents have processed which events.

```sql
event_id UUID
agent_name TEXT
processed_at TIMESTAMP
PRIMARY KEY (event_id, agent_name)
```

### strategy_lineage
Tracks full experiment configuration for reproducibility.

```sql
id UUID PRIMARY KEY
strategy_id TEXT NOT NULL
dataset_version TEXT NOT NULL
backtest_engine_version TEXT NOT NULL
strategy_parameters JSONB NOT NULL
result_metrics JSONB NOT NULL
source_event_id UUID NOT NULL
created_at TIMESTAMP
```

## Routing Rules

Static routing table (in `router.py`):

| Event Type | Target Agent |
|------------|--------------|
| `strategy.created` | `de` |
| `dataset.ready` | `algo` |
| `backtest.completed` | `qa` |
| `qa.validated` | `platform` |
| `platform.deployed` | `tradinghub` |

To add dynamic routing, insert into `routing_rules` table.

## Agent Workflow

```
1. Agent receives notification via sessions_send
   Format: "event:backtest.completed:104"

2. Agent loads event from database

3. Agent performs work

4. Agent emits new event
   hub.emit_event(event_type="qa.validated", ...)

5. Agent marks event as processed
   hub.record_processing(event_id, agent_name)

6. Agent exits
```

## Event Flow Example

```
strategy.created
    ↓
DE Agent (prepares dataset)
    ↓
dataset.ready
    ↓
Algo Agent (runs backtest, records lineage)
    ↓
backtest.completed
    ↓
QA Agent (validates results)
    ↓
qa.validated
    ↓
Platform Agent (deploys strategy)
    ↓
platform.deployed
    ↓
TradingHub (notified of completion)
```

## Running the Demo

```bash
# 1. Set up database
export HUB_DATABASE_URL="postgresql://localhost:5432/hub_events"
createdb hub_events
psql $HUB_DATABASE_URL -f hub/schema.sql

# 2. Run demo workflow
python hub/agents.py

# 3. Check event log
psql $HUB_DATABASE_URL -c "SELECT * FROM events ORDER BY created_at;"

# 4. Check strategy lineage
psql $HUB_DATABASE_URL -c "SELECT * FROM strategy_history;"
```

## API Reference

### HubRouter

```python
from hub import HubRouter

hub = HubRouter()

# Emit event
event_id = hub.emit_event(
    event_type="dataset.ready",
    strategy_id="104",
    payload={"rows": 1000000},
    source_agent="de"
)

# Get event
event = hub.get_event(event_id)

# Get pending events for agent
pending = hub.get_pending_events("algo")

# Get event log
log = hub.get_event_log(strategy_id="104", limit=50)
```

### Agent SDK

```python
from hub.sdk import Agent, Event

class MyAgent(Agent):
    def __init__(self):
        super().__init__("my_agent")
    
    def on_event(self, event: Event):
        # Process event
        result = do_work(event)
        
        # Emit new event
        self.emit_event(
            event_type="work.completed",
            strategy_id=event.strategy_id,
            payload=result
        )
        
        # Mark processed
        self.mark_processed(event.id)

agent = MyAgent()
agent.run()  # Process all pending events
```

### LineageRecorder

```python
# Record experiment for reproducibility
lineage_id = agent.lineage.record(
    strategy_id="104",
    dataset_version="equities_daily_v3",
    backtest_engine_version="engine_v2.1",
    strategy_parameters={"lookback": 20, "threshold": 1.5},
    result_metrics={"sharpe": 1.42, "drawdown": -0.08},
    source_event_id=event.id
)

# Get lineage history
history = agent.lineage.get_lineage("104")

# Compare experiments
comparison = agent.lineage.compare_experiments("104", metric="sharpe")
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HUB_DATABASE_URL` | `postgresql://localhost:5432/hub_events` | PostgreSQL connection string |

## Benefits

- **Zero idle token cost** - Agents only run when triggered
- **Deterministic pipelines** - Clear event flow
- **Full audit history** - Every action logged
- **Reproducible research** - Lineage tracking
- **Scalable coordination** - Easy to add new agents

## Migration from Polling

Replace this:
```python
# OLD: Polling pattern
while True:
    if check_for_work():
        do_work()
    time.sleep(60)
```

With this:
```python
# NEW: Event-driven pattern
from hub.sdk import Agent, handle_notification

class WorkerAgent(Agent):
    def on_event(self, event):
        do_work(event)

# When notification received:
agent = WorkerAgent()
handle_notification(agent, notification)
```
