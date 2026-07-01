#!/usr/bin/env python3
"""
Unit tests for write_pipeline_state.decide_state.

No DB, no network. Verifies the truth table documented in the module:
- ready: every stage succeeded
- partial: some failures but bronze + gold both have at least one output
- failed: bronze produced nothing OR gold produced nothing
- stale: zero stages ran

Run: python3 agents/etl/tests/test_pipeline_state.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import subprocess
import json

HERE = os.path.dirname(os.path.abspath(__file__))
ETL = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, ETL)

from write_pipeline_state import decide_state, parse_list


def test_all_ok_is_ready():
    assert decide_state(
        ['yf'], [], ['clean'], [], ['equity_kpis'], [], ['command'], []
    ) == 'ready'


def test_zero_runs_is_stale():
    assert decide_state([], [], [], [], [], [], [], []) == 'stale'


def test_bronze_empty_is_failed():
    # No bronze succeeded → downstream gold is meaningless.
    assert decide_state(
        [], ['yf', 'binance'], [], ['clean'], [], [], [], []
    ) == 'failed'


def test_gold_empty_is_failed():
    # Bronze + silver ok but gold produced nothing → operator can't trade.
    assert decide_state(
        ['yf'], [], ['clean'], [], [], ['equity_kpis'], [], []
    ) == 'failed'


def test_one_bronze_failure_is_partial():
    # Bronze partial, gold OK → operator has data, just incomplete.
    assert decide_state(
        ['yf', 'binance'], ['ibkr'],
        ['clean'], [],
        ['equity_kpis'], [],
        ['command'], [],
    ) == 'partial'


def test_consumption_only_failures_is_partial():
    # Consumption broken doesn't downgrade past partial — gold layer is fine.
    assert decide_state(
        ['yf'], [], ['clean'], [], ['equity_kpis'], [],
        [], ['command_tab'],
    ) == 'partial'


def test_parse_list_handles_empty_and_spaces():
    assert parse_list('') == []
    assert parse_list(None) == []
    assert parse_list('a,b,c') == ['a', 'b', 'c']
    assert parse_list('a, b ,  c') == ['a', 'b', 'c']
    assert parse_list('a,,b') == ['a', 'b']


def test_cli_writes_valid_json():
    """End-to-end: invoking the CLI writes a parseable state file."""
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, '.state.json')
        rc = subprocess.call([
            sys.executable, os.path.join(ETL, 'write_pipeline_state.py'),
            '--output', out,
            '--bronze-ok', 'yf,binance',
            '--bronze-failed', 'ibkr',
            '--gold-ok', 'equity_kpis',
        ])
        assert rc == 0, "CLI must exit 0 on valid args"
        with open(out) as f:
            payload = json.load(f)
        assert payload['state'] == 'partial'
        assert payload['sources_ok'] == ['yf', 'binance', 'equity_kpis']
        assert payload['sources_failed'] == [{'stage': 'bronze', 'source': 'ibkr'}]
        assert payload['stage_counts']['bronze']['ok'] == 2


def _main():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {fn.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(fns) - failures}/{len(fns)} passed")
    sys.exit(0 if failures == 0 else 1)


if __name__ == "__main__":
    _main()
