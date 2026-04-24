# Event-Driven Agent Architecture
## Domain-Aware Multi-Agent System

**Status**: ✅ Implemented on PostgreSQL (`openclaw_researcher` schema)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                    SHARED INFRASTRUCTURE                        │
│              PostgreSQL + Event Bus (same DB)                   │
├─────────────────────────────────────────────────────────────────┤
│  events table          │  routing_rules table                   │
│  - domain: quant       │  - domain + event_type → target_agent  │
│  - domain: platform    │                                        │
└─────────────────────────────────────────────────────────────────┘
                         │
         ┌───────────────┴───────────────┐
         │                               │
         ▼                               ▼
┌─────────────────────┐    ┌─────────────────────┐
│   QUANT DOMAIN      │    │  PLATFORM DOMAIN    │
│  (Research)         │    │  (Engineering)      │
└─────────────────────┘    └─────────────────────┘
```

---

## Domain Separation

### 1. Quant Research Domain

**Purpose**: Generate, validate, and deploy trading strategies

**Event Flow**:
```
strategy.created ──► de_quant ──► dataset.ready ──► algo_quant ──► backtest.completed
                                                                         │
                                                                         ▼
risk.approved ◄── risk_quant ◄── qa.validated ◄── qa_quant ◄──────────────┘
    │
    ▼
platform_quant ──► platform.deployed ──► tradinghub
```

**Agents**:
| Agent | Role | Consumes | Emits |
|-------|------|----------|-------|
| `de_quant` | Data Engineering | `strategy.created` | `dataset.ready` |
| `algo_quant` | Strategy Research | `dataset.ready` | `backtest.completed` |
| `qa_quant` | Quant Validation | `backtest.completed` | `qa.validated` / `qa.rejected` |
| `risk_quant` | Risk Review | `qa.validated` | `risk.approved` / `risk.rejected` |
| `platform_quant` | Research Deployment | `risk.approved` | `platform.deployed` |

**Event Types**:
- `strategy.created` - New strategy to research
- `dataset.ready` - Data prepared for backtest
- `backtest.completed` - Backtest finished
- `qa.validated` - QA approved results
- `qa.rejected` - QA rejected, back to algo
- `risk.approved` - Risk approved for deployment
- `platform.deployed` - Strategy live

---

### 2. Platform Engineering Domain

**Purpose**: Build, test, and deploy platform features

**Event Flow**:
```
feature.requested ──► platform_dev ──► code.generated ──► qa_code ──► code.tested
                                                                             │
                                                                             ▼
                                                              deployment.completed
                                                                             │
                                                                             ▼
                                                                    platform_monitor
```

**Agents**:
| Agent | Role | Consumes | Emits |
|-------|------|----------|-------|
| `platform_dev` | Feature Development | `feature.requested` | `code.generated` |
| `qa_code` | Code Review | `code.generated` | `code.tested` |
| `platform_ops` | DevOps | `code.tested` | `deployment.completed` |
| `platform_monitor` | SRE/Monitoring | `deployment.completed` | alerts/metrics |

**Event Types**:
- `feature.requested` - New feature to build
- `code.generated` - Code written
- `code.tested` - Tests passed
- `deployment.completed` - Feature live

---

## Database Schema

### Core Tables

#### `events` - Event Log
```sql
id UUID PRIMARY KEY
event_type TEXT NOT NULL      -- e.g., "backtest.completed"
strategy_id TEXT              -- Associated entity
domain TEXT DEFAULT 'quant'   -- 'quant' or 'platform'
payload_json JSONB            -- Event data
source_agent TEXT             -- Who emitted this
created_at TIMESTAMP
```

#### `routing_rules` - Event Routing
```sql
event_type TEXT
target_agent TEXT
domain TEXT DEFAULT 'quant'   -- Separate routing per domain
enabled BOOLEAN
```

#### `event_processing` - Deduplication
```sql
event_id UUID
agent_name TEXT
processed_at TIMESTAMP
PRIMARY KEY (event_id, agent_name)  -- Prevents duplicate processing
```

#### `strategy_lineage` - Experiment Tracking (Quant only)
```sql
id UUID PRIMARY KEY
strategy_id TEXT
dataset_version TEXT
backtest_engine_version TEXT
strategy_parameters JSONB
result_metrics JSONB
source_event_id UUID
created_at TIMESTAMP
```

---

## Usage Examples

### Emit an Event (Quant)

```python
# From Python (using psycopg2)
import psycopg2

conn = psycopg2.connect("postgresql://...")
cur = conn.cursor()

# Emit backtest completed event
cur.execute("""
    SELECT emit_event(
        'backtest.completed',
        'strategy_001',
        '{"sharpe": 1.42, "drawdown": -0.08}',
        'algo_quant',
        'quant'
    )
""")
event_id = cur.fetchone()[0]
conn.commit()
```

### Get Pending Work (Agent Side)

```python
# Agent checks for work
cur.execute("""
    SELECT * FROM get_pending_for_agent('qa_quant', 'quant')
""")
pending = cur.fetchall()

for row in pending:
    print(f"Processing {row.event_type} for {row.strategy_id}")
    # Do work...
    
    # Mark as processed
    cur.execute("""
        SELECT record_processing(%s, 'qa_quant')
    """, (row.event_id,))
```

### Check Pending Work (Views)

```sql
-- All pending work
SELECT * FROM v_pending_work;

-- Quant only
SELECT * FROM v_pending_work_quant;

-- Platform only  
SELECT * FROM v_pending_work_platform;

-- For specific agent
SELECT * FROM get_pending_for_agent('de_quant');
```

---

## Routing Table

Current routing rules:

| Domain | Event Type | Target Agent |
|--------|------------|--------------|
| quant | strategy.created | de_quant |
| quant | dataset.ready | algo_quant |
| quant | backtest.completed | qa_quant |
| quant | qa.validated | risk_quant |
| quant | risk.approved | platform_quant |
| quant | platform.deployed | tradinghub |
| platform | feature.requested | platform_dev |
| platform | code.generated | qa_code |
| platform | code.tested | platform_ops |
| platform | deployment.completed | platform_monitor |
| platform | system.startup | tradinghub |

---

## Views Available

### Event Views
- `v_pending_events` - All unprocessed events
- `v_event_status` - Processing status for all events
- `v_events_quant` - Quant domain events only
- `v_events_platform` - Platform domain events only

### Work Views
- `v_pending_work` - All pending work across domains
- `v_pending_work_quant` - Quant work only
- `v_pending_work_platform` - Platform work only

### Lineage Views
- `v_strategy_history` - Full experiment history
- `v_strategy_full_state` - Combined workflow + events view

---

## Functions

### Core Functions

```sql
-- Emit an event
emit_event(
    p_event_type TEXT,
    p_strategy_id TEXT,
    p_payload JSONB,
    p_source_agent TEXT,
    p_domain TEXT DEFAULT 'quant'
) RETURNS UUID

-- Mark event as processed
record_processing(
    p_event_id UUID,
    p_agent_name TEXT
) RETURNS BOOLEAN

-- Record strategy lineage (Quant)
record_lineage(
    p_strategy_id TEXT,
    p_dataset_version TEXT,
    p_engine_version TEXT,
    p_parameters JSONB,
    p_metrics JSONB,
    p_source_event_id UUID
) RETURNS UUID

-- Get pending work for agent
get_pending_for_agent(
    p_agent_name TEXT,
    p_domain TEXT DEFAULT NULL  -- NULL = all domains
) RETURNS TABLE(...)

-- Get routing targets
get_routing_targets(
    p_event_type TEXT,
    p_domain TEXT DEFAULT 'quant'
) RETURNS TABLE(target_agent TEXT)

-- Get events by domain
get_events_by_domain(
    p_domain TEXT,
    p_limit INTEGER DEFAULT 100
) RETURNS TABLE(...)
```

---

## Migration from Old Schema

The new event-driven tables coexist with the existing workflow tables:

| Old Tables | New Tables | Relationship |
|------------|------------|--------------|
| `strategy_workflow` | `events` | Workflow state + event log |
| `agent_work_queue` | `routing_rules` | Work queue → routing config |
| `workflow_events` | `events` | State changes + domain events |

**Migration Path**:
1. Start emitting events alongside workflow updates
2. Gradually move agents to event-driven pattern
3. Eventually deprecate polling-based workflow tables

---

## Agent Implementation Pattern

```python
class QuantAgent:
    def __init__(self, agent_name, domain='quant'):
        self.agent_name = agent_name
        self.domain = domain
        self.conn = psycopg2.connect("...")
    
    def run(self):
        """Process pending events and exit."""
        cur = self.conn.cursor()
        
        # Get pending work for this agent
        cur.execute("""
            SELECT * FROM get_pending_for_agent(%s, %s)
        """, (self.agent_name, self.domain))
        
        for event in cur.fetchall():
            # Process the event
            result = self.process(event)
            
            # Emit next event
            cur.execute("""
                SELECT emit_event(%s, %s, %s, %s, %s)
            """, (
                result['next_event_type'],
                event.strategy_id,
                json.dumps(result['payload']),
                self.agent_name,
                self.domain
            ))
            
            # Mark as processed
            cur.execute("""
                SELECT record_processing(%s, %s)
            """, (event.event_id, self.agent_name))
        
        self.conn.commit()
```

---

## Benefits

✅ **Zero idle token cost** - Agents only run when triggered  
✅ **Deterministic pipelines** - Clear event flow  
✅ **Full audit trail** - Every action logged  
✅ **Reproducible research** - Lineage tracking  
✅ **Clean separation** - Quant vs Platform isolation  
✅ **Shared infrastructure** - Single DB, multiple domains  
✅ **Independent evolution** - Domains can change independently  

---

## Testing

```bash
# Test quant domain
psql $DB_URL -c "SELECT emit_event('strategy.created', 'test_001', '{}', 'tradinghub', 'quant')"
psql $DB_URL -c "SELECT * FROM v_pending_work_quant"

# Test platform domain
psql $DB_URL -c "SELECT emit_event('feature.requested', 'feature_001', '{}', 'product', 'platform')"
psql $DB_URL -c "SELECT * FROM v_pending_work_platform"
```
