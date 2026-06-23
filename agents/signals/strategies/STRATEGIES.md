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

### `registry.json` entry format

```json
{
  "id": 21,
  "name": "Crypto vol carry",
  "class_path": "strategies.crypto.strategy_21:Strategy21",
  "regime": "CARRY",
  "enabled": false,
  "asset_class": "crypto",
  "params": { },
  "notes": "Registered 2026-06-22. Implement compute_signal() then flip enabled=true."
}
```

| Field | Meaning |
|-------|---------|
| `id` | Integer. Unique. Persists in `gold.strategy_signals.strategy_id`. **Never reuse.** |
| `name` | Short label for dashboards and logs. |
| `class_path` | `module:ClassName`. Must be importable from the `agents/etl/` workspace root. |
| `regime` | One of `TREND`, `MEAN_REV`, `CARRY`, `EVENT`, `FLAT`. Gates when the strategy is active. |
| `enabled` | `true` = runs in cron, writes signals. `false` = imported only, never writes. |
| `asset_class` | `equity` / `crypto` / `fx` / `commodity`. Used for filtering and reporting. |
| `params` | Free-form dict the strategy class can read for thresholds, baskets, etc. Optional. |
| `notes` | Human history / TODO. |

---

## Adding a new strategy in 3 steps

### 1. Register it

```bash
cd agents/etl
python3 strategies/register_strategy.py \
    --id 21 \
    --name "Crypto vol carry" \
    --regime CARRY \
    --asset-class crypto \
    --module strategies.crypto.strategy_21 \
    --class-name Strategy21
```

This:
- Validates against the existing registry (id collisions, allow-listed regime/asset_class).
- Creates a stub `strategies/crypto/strategy_21.py` from a template.
- Appends the entry to `registry.json` with `enabled=false` (safe default).

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

Reference real implementations in `strategies/trend/`:
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

To **delete** a strategy permanently: remove the entry from `registry.json`
AND delete the strategy file. Historical signals in `gold.strategy_signals`
are preserved by `strategy_id`.

---

## Special case — EIA day override

`strategies/base_strategy.py::is_active_today()` has a hardcoded override:
strategy with `id == 12` is forced active on EIA-day events
(`gold.regime_label.severity == 1`). If you move the WTI EIA event drift
strategy to a different id, update that override in base_strategy.py.

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
