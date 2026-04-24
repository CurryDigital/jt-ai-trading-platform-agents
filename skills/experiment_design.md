# Skill: Experiment Design

## Purpose
Defines how the Exp. Manager generates new experiments, when to
explore vs exploit, how to prune dead-end families, and what
constitutes a valid next-generation param_set.

Load this skill: Exp. Manager only.

---

## Two phases of search

### Phase 1 — Broad search (< 50 total experiments)
Random and grid search. Goal: map the parameter space.
- Each variant changes exactly ONE parameter from the parent
- Vary: entry_threshold (±25%), lookback_window (±5 days), exit_threshold (±20%)
- Generate 3 variants per passing strategy, 1 variant per failing strategy
- Reason for 1 on fail: failing strategies still have a neighbourhood worth probing

### Phase 2 — Focused exploitation (≥ 50 total experiments)
Bayesian-style updates. Goal: converge on best region.
- Identify top 10% of strategy_lineage by sharpe_oos
- Generate variants only around these top performers
- Use tighter perturbations: ±10% on thresholds, ±2 days on lookback
- Generate 5 variants per top performer

---

## Variant generation rules (both phases)

1. Never re-run an identical param_set (check strategy_lineage + events, last 30 days)
2. Never generate a variant if >10 experiments are in_progress (flood control)
3. Always increment generation counter: variant.generation = parent.generation + 1
4. Always set parent_experiment_id: variant.parent_experiment_id = parent.experiment_id
5. Never change strategy_type or asset_universe in a variant — only numeric params
6. Clamp all parameters to valid ranges (see below)

---

## Parameter valid ranges

| param | min | max | step |
|-------|-----|-----|------|
| lookback_window | 5 | 120 | 1 day |
| entry_threshold | 0.5 | 5.0 | 0.1 |
| exit_threshold | 0.1 | 3.0 | 0.1 |

Never emit a param_set with values outside these ranges.
Clamp silently if perturbation would exceed bounds.

---

## Family pruning

A family = all experiments sharing the same strategy_type + asset_universe.

Prune a family (stop generating variants) when:
- Family has ≥ 20 experiments AND QA pass rate < 5%
- Log: "Pruning family: momentum/AAPL,MSFT,GOOGL — 22 experiments, 0% pass rate"

Expand a family (increase variant count) when:
- Family QA pass rate > 30% over last 10 experiments
- Log: "Expanding family: mean_reversion/large_cap — 8/10 recent pass rate"

---

## Nightly autonomous cycle (triggered by HEARTBEAT)

When triggered by the heartbeat (not by a qa.validated event):

1. Query strategy_lineage for entries with sharpe_oos > 0.5 in last 7 days
2. If entries exist: generate 5 variants around the top performer (by sharpe_oos)
3. If no entries: run a broad random search — generate 3 fresh experiments
   with randomly sampled params from valid ranges across 2–3 strategy types
4. Report one-line summary:
   "Nightly cycle: 5 variants generated from strategy {id} (Sharpe OOS {x})."
   or
   "Nightly cycle: no recent lineage — seeding 3 random experiments."

---

## Experiment context (always include in experiment.started payload)

```json
{
  "experiment_id": "new-uuid",
  "param_set": { ... },
  "generation": 4,
  "parent_experiment_id": "parent-uuid-or-null",
  "source": "exp_manager"   // or "idea_intake" for human-originated
}
```

The `source` field lets the operator distinguish autonomous experiments
from human-submitted ideas in status queries.

---

## What not to do

- Never emit > 10 experiments in a single cycle (flood control)
- Never generate variants from rejected strategies in Phase 2
- Never modify asset_universe or strategy_type in a variant
- Never run if in_progress count ≥ FLOOD_CONTROL_LIMIT (currently 50)
