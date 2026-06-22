#!/usr/bin/env python3
"""
Daily Signal Runner — Goal 2
============================
Loops through all 20 strategies, calls run() and save().
Imports real TREND strategies from strategies/trend/.
Remaining 13 strategies use stubs.
Prints a summary table at the end.
"""
import sys, os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')
sys.path.insert(0, WORKSPACE)
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection

# Import TREND strategies (real implementations)
from strategies.trend.strategy_01 import Strategy01
from strategies.trend.strategy_02 import Strategy02
from strategies.trend.strategy_06 import Strategy06
from strategies.trend.strategy_11 import Strategy11
from strategies.trend.strategy_15 import Strategy15
from strategies.trend.strategy_16 import Strategy16
from strategies.trend.strategy_18 import Strategy18

# Import stubs for remaining strategies
from strategies.stubs import (
    Strategy03, Strategy04, Strategy05,
    Strategy07, Strategy08, Strategy09, Strategy10,
    Strategy12, Strategy13, Strategy14,
    Strategy17, Strategy19, Strategy20,
)

ALL_STRATEGIES = [
    Strategy01, Strategy02, Strategy03, Strategy04, Strategy05,
    Strategy06, Strategy07, Strategy08, Strategy09, Strategy10,
    Strategy11, Strategy12, Strategy13, Strategy14, Strategy15,
    Strategy16, Strategy17, Strategy18, Strategy19, Strategy20,
]


def print_summary(results: list, regime: str):
    """Print formatted summary table."""
    today = results[0]['date'] if results else 'N/A'
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


def main():
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
    for StratClass in ALL_STRATEGIES:
        try:
            strat = StratClass(conn)
            result = strat.run()
            strat.save(result)
            results.append(result)
        except Exception as e:
            print(f"  ERROR strategy {StratClass.__name__}: {e}")

    print_summary(results, regime)
    conn.close()
    print(f"\n✅ Signal run complete — {len(results)} strategies processed")


if __name__ == '__main__':
    main()
