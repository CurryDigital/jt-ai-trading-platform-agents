# Param Set Specification

The param_set is the unit of experiment identity. Every agent that
reads, writes, or validates experiments uses this spec.

---

## Canonical fields

| field | type | required | valid range | default |
|-------|------|----------|-------------|---------|
| strategy_type | string | YES | momentum, mean_reversion, breakout, pairs, trend | — |
| lookback_window | int | YES | 5–120 (days) | by strategy_type |
| entry_threshold | float | YES | 0.5–5.0 | by strategy_type |
| exit_threshold | float | YES | 0.1–3.0 | by strategy_type |
| asset_universe | list[str] | YES | 1–20 tickers | — |
| date_range.start | date string | YES | YYYY-MM-DD | 3 years ago |
| date_range.end | date string | YES | YYYY-MM-DD | yesterday |

## Defaults by strategy_type

| strategy_type | lookback_window | entry_threshold | exit_threshold |
|---------------|----------------|----------------|----------------|
| momentum | 20 | 1.5 | 0.5 |
| mean_reversion | 20 | 2.0 | 0.5 |
| breakout | 14 | 1.0 | 0.3 |
| pairs | 30 | 2.0 | 0.5 |
| trend | 50 | 1.5 | 0.5 |

## Serialisation rules

When comparing two param_sets for duplicate detection:
- Serialise both as JSON with keys sorted (sort_keys=True)
- Sort asset_universe alphabetically before serialising
- Compare the resulting strings

```python
import json
canonical = json.dumps({
    'strategy_type':   ps['strategy_type'],
    'lookback_window': ps['lookback_window'],
    'entry_threshold': ps['entry_threshold'],
    'exit_threshold':  ps['exit_threshold'],
    'asset_universe':  sorted(ps['asset_universe']),
    'date_range':      ps['date_range'],
}, sort_keys=True)
```

## Storage in events table

param_set is stored inside payload_json:
```sql
payload_json->'param_set'         -- jsonb
payload_json->>'param_set'        -- text (for JSON parsing in Python)
```

Not a direct column. Always access via payload_json.

## Storage in strategy_lineage

Written to both strategy_parameters AND param_set columns.
Both are jsonb. They should always be identical.
(Two columns exist for backward compatibility.)

## experiment.started payload (full structure)

```json
{
  "experiment_id": "uuid",
  "param_set": {
    "strategy_type": "momentum",
    "lookback_window": 20,
    "entry_threshold": 1.5,
    "exit_threshold": 0.5,
    "asset_universe": ["AAPL", "MSFT", "GOOGL"],
    "date_range": {
      "start": "2022-01-01",
      "end": "2023-12-31"
    }
  },
  "generation": 1,
  "parent_experiment_id": null,
  "source": "idea_intake"
}
```

## Variant generation constraints (Exp. Manager)

When generating a variant from a parent param_set:
- MUST keep strategy_type unchanged
- MUST keep asset_universe unchanged
- MAY change: lookback_window, entry_threshold, exit_threshold, date_range
- MUST clamp to valid ranges after perturbation
- MUST increment generation: variant.generation = parent.generation + 1
- MUST set parent_experiment_id = parent.experiment_id
