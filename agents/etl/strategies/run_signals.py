#!/usr/bin/env python3
"""
Daily Signal Runner
===================
Loads the strategy registry, instantiates every enabled strategy, calls
run() + save(), and prints a summary table.

2026-06-22: refactored to read strategies/registry.json instead of
hardcoding `from strategies.trend.strategy_01 import Strategy01` for
20 classes. Adding a new strategy now requires no edits to this file.

To onboard a new strategy:
  python3 strategies/register_strategy.py --id 21 --name "..." --regime TREND --asset-class equity
Then implement strategies/trend/strategy_21.py::Strategy21 and flip
`enabled: true` in registry.json. The next cron picks it up.
"""

import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from strategies.registry_loader import (
    load_enabled_strategies, import_strategy_class, RegistryError,
)


def print_summary(results: list, regime: str) -> None:
    if not results:
        print(f"  Date: N/A  Regime: {regime}  (no strategies ran)")
        return
    today = results[0]['date']
    print(f"\n  Date: {today}")
    print(f"  Regime: {regime}")
    print(f"  ┌─────┬──────────────────────────┬────────┬────────┐")
    print(f"  │ ID  │ Strategy                 │ Signal │ Active │")
    print(f"  ├─────┼──────────────────────────┼────────┼────────┤")
    for r in results:
        sig = f"{r['signal']:+d}" if r['signal'] != 0 else "  0"
        act = "  ✓" if r['active'] else "  —"
        print(f"  │ {r['strategy_id']:>2d}  │ {r['name']:<24s} │ {sig:>4s}   │ {act:>4s}   │")
    print(f"  └─────┴──────────────────────────┴────────┴────────┘")


def main() -> int:
    try:
        enabled = load_enabled_strategies()
    except RegistryError as e:
        print(f"FATAL: strategy registry invalid: {e}", file=sys.stderr)
        return 2

    if not enabled:
        print("⚠️  No enabled strategies in registry.json — nothing to do.", file=sys.stderr)
        return 0

    conn = get_connection()

    # Get today's regime for display
    cur = conn.cursor()
    cur.execute("""
        SELECT regime FROM gold.regime_label
        WHERE date = (SELECT MAX(date) FROM gold.regime_label)
    """)
    row = cur.fetchone()
    regime = row[0] if row else 'UNKNOWN'

    results = []
    n_errors = 0
    for entry in enabled:
        try:
            StratClass = import_strategy_class(entry)
        except RegistryError as e:
            print(f"  ERROR loading strategy {entry.id} ({entry.name}): {e}", file=sys.stderr)
            n_errors += 1
            continue
        try:
            strat = StratClass(conn)
            result = strat.run()
            strat.save(result)
            results.append(result)
        except Exception as e:
            print(f"  ERROR strategy {entry.id} ({entry.name}): {e}", file=sys.stderr)
            n_errors += 1

    print_summary(results, regime)
    conn.close()
    print(f"\n✅ Signal run complete — {len(results)}/{len(enabled)} strategies processed "
          f"({n_errors} errors)")
    return 0 if n_errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
