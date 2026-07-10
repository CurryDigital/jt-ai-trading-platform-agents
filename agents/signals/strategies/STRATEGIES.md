# Strategies — onboarding guide

This is the single document an operator needs to add a new trading strategy.
The old workflow required hand-edits to **three Python files** (`run_signals.py`,
`stubs.py`, `regime_rules.py::STRATEGY_MAP`) plus the strategy file itself.
The new workflow is **one CLI command + one file**.

---

## How the registry works

`registry.json` is the source of truth. Three pieces of the daily cron read it:

- `strategies/run_signals.py` — iterates over enabled strategies, calls `run()` + `save()`.
- `regime/regime_rules.py::STRATEGY_MAP` — derived from `registry.json`, gates strategies by regime.
- `strategies/registry_loader.py` — the only place that validates + imports.

If you change `registry.json`, the next 30-minute cron picks it up. **No restart, no deploy.**

### Folder layout — maturity tiers

Strategy files live under a tier folder that mirrors the frontend/DB
`gold.strategy_registry.priority` vocabulary:

```
strategies/
  experimental/   ← every new strategy starts here (priority=EXPERIMENTAL)
  near_golden/    ← passed OOS backtest gates, pending approval (priority=NEAR_GOLDEN)
  golden/         ← approved, paper/live capital assigned (priority=GOLDEN)
```

**Promotion is a deliberate, single-commit act**: `git mv` the file to the
next tier folder, update `tier` + `class_path` in `registry.json`, and update
the DB row's `priority`. The loader refuses a registry whose `tier` claim
doesn't match the folder in `class_path`, so the tree can't silently lie
about maturity.

### `registry.json` entry format

```json
{
  "id": 21,
  "name": "Crypto vol carry",
  "class_path": "strategies.experimental.strategy_21:Strategy21",
  "tier": "experimental",
  "regime": "CARRY",
  "enabled": false,
  "asset_class": "crypto",
  "params": { },
  "notes": "Registered 2026-07-10. Implement compute_signal() then flip enabled=true."
}
```

| Field | Meaning |
|-------|---------|
| `id` | Integer. Unique. Persists in `gold.strategy_signals.strategy_id`. **Never reuse** — deleted strategies' ids move to the top-level `retired_ids` list and the loader rejects re-use. |
| `name` | Short label for dashboards and logs. |
| `class_path` | `module:ClassName`. Must be importable from the `agents/signals/` root. |
| `tier` | `experimental` / `near_golden` / `golden`. Must match the folder in `class_path`. |
| `regime` | One of `TREND`, `MEAN_REV`, `CARRY`, `EVENT`, `FLAT`. Gates when the strategy is active. |
| `enabled` | `true` = runs in cron, writes signals. `false` = imported only, never writes. |
| `asset_class` | `equity` / `crypto` / `fx` / `commodity`. Used for filtering and reporting. |
| `params` | Free-form dict the strategy class can read for thresholds, baskets, etc. Optional. |
| `notes` | Human history / TODO. |

---

## Adding a new strategy in 3 steps

### 1. Register it

```bash
cd agents/signals
python3 strategies/register_strategy.py \
    --id 21 \
    --name "Crypto vol carry" \
    --regime CARRY \
    --asset-class crypto \
    --class-name Strategy21
```

This:
- Validates against the existing registry (id collisions, retired ids, allow-listed regime/asset_class).
- Creates a stub `strategies/experimental/strategy_21.py` from a template (new strategies always start experimental).
- Appends the entry to `registry.json` with `enabled=false` and `tier=experimental` (safe defaults).

### 2. Implement `compute_signal()`

Open the generated file. The contract:

```python
def compute_signal(self) -> int:
    # Always call is_active_today() first.
    # Return 0 if not active.
    if not self.is_active_today():
        return 0

    # Your signal logic here.
    # Returns +1 (long), -1 (short), 0 (flat).
    ...
```

Reference real implementations in `strategies/experimental/`:
- `strategy_01.py` — Dual EMA crossover (basket of equity ETFs)
- `strategy_02.py` — 52-week high momentum
- `strategy_06.py` — BTC Donchian breakout

### 3. Validate and enable

```bash
# Lints the registry (no DB needed)
python3 -c "from strategies.registry_loader import load_registry; load_registry()"

# Run the unit tests
python3 tests/test_registry_loader.py
```

Once green, flip `enabled: true` in `registry.json` for your new entry. The
next cron cycle will start writing signals for it.

---

## Disabling a strategy

Edit `registry.json`, set `"enabled": false`. The strategy stays in the
registry (so its id is reserved and its history is preserved) but stops
contributing signals. No code edit needed.

To **delete** a strategy permanently: remove the entry from `registry.json`,
add its id to the top-level `retired_ids` list, and delete the strategy file.
Historical signals in `gold.strategy_signals` are preserved by `strategy_id`,
which is exactly why the id must never be reused.

---

## What `params` is for

The `params` dict in each registry entry is a forward-looking field. Today
most strategies still hardcode their parameters inside the class file
(e.g. `strategy_01.py::__init__` sets `self.basket = ['SPY','QQQ',...]`).
The follow-up is to migrate each strategy class to read from `self.params`
instead, so an operator can tune thresholds and baskets without editing code.

Migration pattern:

```python
class Strategy01(BaseStrategy):
    def __init__(self, conn, params=None):
        super().__init__(conn, 1, "Dual EMA crossover")
        params = params or {}
        self.basket = params.get('basket', ['SPY', 'QQQ', 'IWM', 'GLD', 'TLT'])
        self.ema_fast = int(params.get('ema_fast', 10))
        self.ema_slow = int(params.get('ema_slow', 50))
        self.delta_long = float(params.get('delta_long_threshold', 0.001))
        self.delta_short = float(params.get('delta_short_threshold', -0.001))
```

Then `registry_loader.import_strategy_class()` + `run_signals.py` would pass
`entry.params` in — change that in a follow-up commit alongside the strategy migration.
