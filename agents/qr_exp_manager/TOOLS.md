# TOOLS.md — qr_exp_manager

## Database

- **Schema:** `openclaw_researcher`
- **Auth:** static password (`/home/ubuntu/.openclaw/.env::DB_PASSWORD`). NOT IAM/boto3.

## Tables / views I read

- `v_exp_manager_work` — primary reactive queue
- `strategy_workflow` — flood-control count
- `events` (event_type='qa.validated', `experiment.started`) — family-health stats + dedup
- `strategy_lineage` (last 7 days, sharpe_oos > 0.5) — nightly top-performer seeding
- `workflow_events` — self-gate markers for nightly + weekly

## Tables I write

| Table | Operation | Trigger |
|-------|-----------|---------|
| `strategy_workflow` | INSERT (status='pending') | per generated variant |
| `events`            | INSERT (`experiment.started`) | per generated variant |
| `events`            | INSERT (`etl.operator_alert`) | weekly summary |
| `event_processing`  | INSERT (`qr_exp_manager`) | end of reactive phase |
| `workflow_events`   | INSERT (`nightly_cycle_complete`) | end of nightly phase |
| `workflow_events`   | INSERT (`weekly_summary_complete`) | end of weekly phase |

## Constants

```python
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_EXP_MANAGER as AGENT_ID,
    FLOOD_CONTROL_LIMIT,             # 50
    MAX_VARIANTS_PER_CYCLE,          # 5
    EXP_PHASE1_THRESHOLD,            # 0.6
    EXP_PHASE1_VARIANTS_PASS,        # 3
    EXP_PHASE1_VARIANTS_FAIL,        # 2
    EXP_PHASE2_VARIANTS,             # 5
    EXP_DUPLICATE_LOOKBACK_DAYS,     # 30
    EXP_PRUNE_PASS_RATE,             # 0.05
    EXP_EXPAND_PASS_RATE,            # 0.30
    EXP_PRUNE_MIN_EXPERIMENTS,       # 20
    EXP_NIGHTLY_TOP_SHARPE,          # 0.5
    EXP_NIGHTLY_LOOKBACK_DAYS,       # 7
    EXP_NIGHTLY_FALLBACK_COUNT,      # 3
    PARAM_LOOKBACK_MIN, PARAM_LOOKBACK_MAX,
    PARAM_ENTRY_MIN, PARAM_ENTRY_MAX,
    PARAM_EXIT_MIN, PARAM_EXIT_MAX,
)
```

## Filesystem

- `memory/YYYY-MM-DD.md` — append per cycle: parent, variants, mutations
- `MEMORY.md::dead_ends` — append on family pruning

## Denied

- No `sessions_send` (hub-only).
- No write to `strategy_lineage` (qr_qa only).
- No direct operator messaging — Phase C emits `etl.operator_alert` and qr_idea_intake delivers.
- No bypass of flood control. Generating into an over-capacity pipeline produces stuck workflows, not progress.
