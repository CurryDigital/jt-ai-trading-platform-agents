#!/usr/bin/env python3
"""
check_pipeline_refs.py — CI guard for the refresh/cron shell scripts.

Two bug classes actually shipped and failed silently on every cron run
before this check existed (2026-07 review):
  1. A run_gold line pointing at a Python file that had been deleted
     (gold/strategy/ingest_small_cap_credit_spread.py) — failed daily.
  2. run_gold lines passing .sql files to the PYTHON interpreter
     (build_etf_*_paper_signal.sql) — SyntaxError on every run since added.

This script parses every `run_bronze/run_silver/run_gold/run_consumption/
run_pipeline_step "<name>" "<script>"` call in the checked shell scripts and
asserts:
  - the referenced file exists (resolved relative to the shell script's dir,
    matching each script's `cd` behavior), and
  - the extension is runnable by that runner (.py — these runners all invoke
    ${PYTHON} <script>; SQL must go through run_pipeline_sql / db.py).

Exit 0 = clean. Exit 1 = violations printed.
"""
from __future__ import annotations

import os
import re
import sys

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

# shell script → the directory its run_* calls resolve paths against
CHECKED_SHELLS = {
    "agents/etl/daily_refresh.sh":        "agents/etl",
    "agents/etl/hourly_refresh.sh":       "agents/etl",
    "agents/etl/weekly_refresh.sh":       "agents/etl",
    "agents/signals/run_signal_cycle.sh": "agents/signals",
    "agents/signals/refresh_now.sh":      "agents/signals",
}

# runner name → allowed extensions of the script argument
PYTHON_RUNNERS = {
    "run_bronze", "run_silver", "run_gold", "run_consumption",
    "run_pipeline_step", "step",
}
SQL_RUNNERS = {"run_pipeline_sql", "sql_step"}

# Calls whose script argument contains a shell variable ("${VAR}/...") are
# skipped — those paths are runtime-guarded with [ -f ] at the call sites.
CALL_RE = re.compile(
    r'^\s*(run_bronze|run_silver|run_gold|run_consumption|run_pipeline_step|run_pipeline_sql|step|sql_step)'
    r'\s+"[^"]*"\s+"([^"$]+)"'
)


def check_shell(shell_rel: str, base_rel: str) -> list:
    problems = []
    shell_abs = os.path.join(REPO, shell_rel)
    base_abs = os.path.join(REPO, base_rel)
    with open(shell_abs) as f:
        for lineno, line in enumerate(f, 1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            m = CALL_RE.match(line)
            if not m:
                continue
            runner, script = m.group(1), m.group(2)
            target = os.path.normpath(os.path.join(base_abs, script))
            loc = f"{shell_rel}:{lineno}"
            if not os.path.isfile(target):
                problems.append(f"{loc}: {runner} references missing file {script!r}")
                continue
            ext = os.path.splitext(script)[1]
            if runner in PYTHON_RUNNERS and ext != ".py":
                problems.append(
                    f"{loc}: {runner} feeds {script!r} to the Python interpreter "
                    f"({ext} is not runnable Python — use run_pipeline_sql for SQL)"
                )
            if runner in SQL_RUNNERS and ext != ".sql":
                problems.append(
                    f"{loc}: {runner} expects a .sql file, got {script!r}"
                )
    return problems


def main() -> int:
    all_problems = []
    n_calls = 0
    for shell_rel, base_rel in CHECKED_SHELLS.items():
        if not os.path.isfile(os.path.join(REPO, shell_rel)):
            all_problems.append(f"{shell_rel}: checked shell script itself is missing")
            continue
        with open(os.path.join(REPO, shell_rel)) as f:
            n_calls += sum(1 for l in f if CALL_RE.match(l) and not l.lstrip().startswith("#"))
        all_problems.extend(check_shell(shell_rel, base_rel))

    if all_problems:
        print(f"❌ {len(all_problems)} pipeline reference problem(s):")
        for p in all_problems:
            print(f"  {p}")
        return 1
    print(f"✅ pipeline references OK ({n_calls} run_* calls across {len(CHECKED_SHELLS)} shells)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
