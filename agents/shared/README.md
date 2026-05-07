# agents/shared — Shared Knowledge and Utilities

This directory is the single source of truth for anything used by
more than one agent. If a value, schema definition, or utility
appears in two places, it belongs here.

---

## Contents

| file | purpose | used by |
|------|---------|---------|
| `__init__.py` | Makes this a Python package | (import machinery) |
| `db.py` | IAM-authenticated RDS connection | All pipeline agents, all ETL scripts |
| `constants.py` | All pipeline-wide constants and limits | All pipeline agents |
| `schema.md` | Authoritative column names for every table | All agents (reference) |
| `README.md` | This file | Humans and agents reading the workspace |

---

## How to import in an agent

All pipeline agents add the workspace root to sys.path:
```python
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
```

Then import directly:
```python
from agents.shared.db import get_connection
from agents.shared.constants import SCHEMA, FLOOD_CONTROL_LIMIT, TIMEOUT_THRESHOLDS
```

ETL scripts (which run from inside `agents/etl/`) use the local copy:
```python
sys.path.insert(0, 'shared/scripts')
from db import get_connection
```
The `agents/etl/shared/scripts/db.py` file is kept in sync with
`agents/shared/db.py` — they are identical. Do not diverge them.

---

## Rules for this directory

1. **Never add agent-specific logic here.** If it's only used by one
   agent, it belongs in that agent's file or `.md` spec.

2. **Constants over magic numbers.** If a number appears in an agent
   file and it has a name (FLOOD_CONTROL_LIMIT, TIMEOUT_BACKTEST_COMPLETED),
   it lives in `constants.py`. The agent imports it.

3. **schema.md is read-only for agents.** Agents read it to confirm
   column names. They do not update it — schema changes go through
   a migration SQL file and then this doc is updated manually.

4. **Keep db.py in sync.** If you update `agents/shared/db.py`,
   immediately copy it to `agents/etl/shared/scripts/db.py`.
   They must be identical. The ETL layer depends on the ETL copy.

---

## What does NOT belong here

- Agent souls → `souls/`
- Agent specs → `agents/*.md` or `agents/pipeline/*.md`
- Collaboration rules, skill definitions → `skills/`
- Hub routing and SDK → `hub/`
- Architecture docs → `docs/`
