#!/usr/bin/env python3
"""
write_pipeline_state.py
=======================
Aggregates per-stage failure lists from daily_refresh.sh into a single
.state.json file that sync_gold_layer_state.py uploads to the DB.

This script is the *only* place that decides the overall gold_layer_state
('ready' | 'partial' | 'stale' | 'failed' | 'locked'). It replaces the
previous behaviour where sync_gold_layer_state.py silently defaulted to
state='fresh' when .state.json was missing — which was the root cause of
"data is stale but gold_layer_state.state says fresh".

Usage from bash:
    python3 write_pipeline_state.py \
        --output .state.json \
        --bronze-ok "binance,fmp,yfinance,fred" \
        --bronze-failed "ibkr" \
        --silver-ok "clean_unified_prices,clean_unified_earnings" \
        --silver-failed "" \
        --gold-ok "equity_kpis,stock_metrics" \
        --gold-failed "" \
        --consumption-ok "command,lab" \
        --consumption-failed ""

Empty strings mean "no entries". Comma-separated lists are tolerated with
or without spaces.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone


def parse_list(s: str | None) -> list[str]:
    if not s:
        return []
    return [item.strip() for item in s.split(',') if item.strip()]


def decide_state(
    bronze_ok: list[str], bronze_failed: list[str],
    silver_ok: list[str], silver_failed: list[str],
    gold_ok: list[str], gold_failed: list[str],
    consumption_ok: list[str], consumption_failed: list[str],
) -> str:
    """
    Truth table — what does the operator's dashboard see?

    - ready:   every stage succeeded, no failures anywhere.
    - partial: some failures, but at least one source per stage succeeded
               AND the gold stage produced at least one output.
    - failed:  the gold stage produced zero outputs OR bronze produced
               zero outputs (downstream gold is meaningless without bronze).
    - stale:   no stages ran at all (the script aborted before bronze).

    Consumption failures alone don't downgrade past 'partial' — operator
    can still query the gold layer; they only break specific frontend tabs.
    """
    total_ran = (
        len(bronze_ok) + len(bronze_failed)
        + len(silver_ok) + len(silver_failed)
        + len(gold_ok) + len(gold_failed)
        + len(consumption_ok) + len(consumption_failed)
    )
    if total_ran == 0:
        return 'stale'

    if not bronze_ok or not gold_ok:
        return 'failed'

    any_failed = bool(
        bronze_failed or silver_failed or gold_failed or consumption_failed
    )
    return 'partial' if any_failed else 'ready'


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--output', default='.state.json',
                    help='Path to write the state JSON (default: .state.json)')
    for stage in ('bronze', 'silver', 'gold', 'consumption'):
        ap.add_argument(f'--{stage}-ok', default='',
                        help=f'Comma-separated {stage} sources that succeeded')
        ap.add_argument(f'--{stage}-failed', default='',
                        help=f'Comma-separated {stage} sources that failed')
    args = ap.parse_args()

    stages = {
        s: {
            'ok':     parse_list(getattr(args, f'{s}_ok')),
            'failed': parse_list(getattr(args, f'{s}_failed')),
        }
        for s in ('bronze', 'silver', 'gold', 'consumption')
    }

    state = decide_state(
        stages['bronze']['ok'],     stages['bronze']['failed'],
        stages['silver']['ok'],     stages['silver']['failed'],
        stages['gold']['ok'],       stages['gold']['failed'],
        stages['consumption']['ok'], stages['consumption']['failed'],
    )

    sources_failed = []
    for stage, results in stages.items():
        for name in results['failed']:
            sources_failed.append({'stage': stage, 'source': name})

    sources_ok = [name for results in stages.values() for name in results['ok']]

    payload = {
        'state':           state,
        'sources_ok':      sources_ok,
        'sources_failed':  sources_failed,
        'locked_since':    None,
        'completed_at':    datetime.now(timezone.utc).isoformat(),
        'stage_counts': {
            stage: {'ok': len(r['ok']), 'failed': len(r['failed'])}
            for stage, r in stages.items()
        },
    }

    out_path = os.path.abspath(args.output)
    with open(out_path, 'w') as f:
        json.dump(payload, f, indent=2, sort_keys=True)

    print(f"Pipeline state: {state}  "
          f"(bronze ok={len(stages['bronze']['ok'])}/failed={len(stages['bronze']['failed'])}, "
          f"silver ok={len(stages['silver']['ok'])}/failed={len(stages['silver']['failed'])}, "
          f"gold ok={len(stages['gold']['ok'])}/failed={len(stages['gold']['failed'])}, "
          f"consumption ok={len(stages['consumption']['ok'])}/failed={len(stages['consumption']['failed'])}) "
          f"→ {out_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
