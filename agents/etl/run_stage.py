#!/usr/bin/env python3
"""
run_stage.py — the ONE runner for the declarative pipeline_manifest.json
(PIPELINE_DESIGN.md principle 5: explicit over implicit).

Replaces the glob-sweeps and the four near-identical run_bronze/run_silver/
run_gold/run_consumption functions duplicated across daily/hourly/weekly_
refresh.sh. What runs, when, and with what timeout is now data in one file,
reviewable in a single diff — no more "for f in dir/*.py" that silently
picks up a new (or double-counted) script, and no more '# CADENCE: weekly'
comment hack (cadence is a field).

Usage:
    python3 run_stage.py --cadence daily                 # all stages, daily
    python3 run_stage.py --cadence hourly --stage silver # one stage
    python3 run_stage.py --cadence daily --dry-run       # print plan, run nothing
    python3 run_stage.py --cadence daily --state-out .state.json

Semantics preserved from the shells:
  - per-step timeout via subprocess (SIGKILL after +10s grace, like `timeout -k`)
  - stage order from manifest.stages_order; step order = manifest order
  - .py runs via ${PYTHON:-python3}; .sql runs through db.py
  - honest exit: non-zero if any step failed; writes .state.json via the
    existing write_pipeline_state.decide_state contract so
    sync_gold_layer_state.py is unchanged.

NOT covered (kept in the thin shell wrapper): the IBKR EC2 ssh runner (not a
python/sql script) and the env/venv/PATH preamble.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_MANIFEST = os.path.join(HERE, "pipeline_manifest.json")
PYTHON = os.environ.get("PYTHON") or sys.executable or "python3"
KILL_GRACE = 10  # seconds after timeout before SIGKILL, mirrors `timeout -k 10s`

VALID_STAGES = ("bronze", "silver", "gold", "consumption")
VALID_CADENCES = ("daily", "hourly", "weekly")


def load_manifest(path):
    with open(path) as f:
        return json.load(f)


def select_steps(manifest, cadence, stage=None):
    steps = [s for s in manifest["steps"]
             if s.get("enabled", True) and s["cadence"] == cadence
             and (stage is None or s["stage"] == stage)]
    order = {s: i for i, s in enumerate(manifest.get("stages_order", VALID_STAGES))}
    # stable: stage order first, original manifest order within a stage
    return sorted(steps, key=lambda s: order.get(s["stage"], 99))


def _run_py(script_abs, args, timeout):
    return subprocess.run([PYTHON, script_abs, *args], timeout=timeout).returncode


def _run_sql(script_abs, timeout):
    # Execute .sql through db.py — never the Python interpreter (the bug this
    # whole design guards against). Inline so no extra file is needed.
    driver = (
        "import sys; sys.path.insert(0, r'%s');"
        "from db import get_connection;"
        "sql=open(r'%s').read();"
        "c=get_connection();\n"
        "try:\n"
        " cur=c.cursor(); cur.execute(sql); c.commit()\n"
        "finally:\n"
        " c.close()\n"
        "print('applied %s')"
    ) % (os.path.join(HERE, "shared", "scripts"), script_abs, os.path.basename(script_abs))
    return subprocess.run([PYTHON, "-c", driver], timeout=timeout).returncode


# ── Freshness rollout (PIPELINE_DESIGN.md principle 4) ────────────────────
# The staleness dashboard was blind to the whole silver layer + a couple of
# bronze jobs because freshness marking was opt-in per script. The runner
# closes that gap by construction: after every step it stamps
# gold.source_freshness — EXCEPT for steps whose script already self-stamps
# (ingest_binance, fmp, yfinance_prices, ...), which own their freshness with
# meaningful source names. Detection is a cheap one-time grep per script.
# Everything here soft-fails: freshness bookkeeping must never fail a step.
_self_stamp_cache = {}


def _script_self_stamps(script_abs) -> bool:
    if script_abs not in _self_stamp_cache:
        try:
            with open(script_abs) as f:
                body = f.read()
            _self_stamp_cache[script_abs] = (
                "mark_source_refreshed" in body or "freshness_guard" in body
            )
        except Exception:
            _self_stamp_cache[script_abs] = True  # assume yes → don't double-stamp
    return _self_stamp_cache[script_abs]


def _stamp_freshness(step, ok):
    """Mark gold.source_freshness for a manifest step the script didn't self-stamp."""
    script_abs = os.path.join(HERE, step["script"])
    if _script_self_stamps(script_abs):
        return
    source = f"{step['stage']}:{os.path.splitext(os.path.basename(step['script']))[0]}"
    freq = {"daily": "daily", "hourly": "hourly", "weekly": "weekly"}.get(step["cadence"], "daily")
    try:
        sys.path.insert(0, os.path.join(HERE, "shared", "scripts"))
        from db import get_connection
        from freshness import mark_source_refreshed
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn, source=source, expected_frequency=freq,
                error=None if ok else "pipeline step failed (see run_stage log)",
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"    (freshness stamp skipped for {source}: {e})")


def run_step(step, dry_run):
    script = step["script"]
    script_abs = os.path.join(HERE, script)
    args = step.get("args", [])
    timeout = step["timeout"]
    label = f"{step['stage']}:{step['name']}"
    if dry_run:
        a = (" " + " ".join(args)) if args else ""
        stamp = "" if _script_self_stamps(script_abs) else "  [runner-stamps-freshness]"
        print(f"  [dry-run] {label}  ->  {script}{a}  (timeout {timeout}s){stamp}")
        return True
    if not os.path.isfile(script_abs):
        print(f"  ⚠️ {label}: script not found ({script}) — skipping")
        return False
    print(f"→ {label} (budget {timeout}s)")
    try:
        if script.endswith(".sql"):
            rc = _run_sql(script_abs, timeout + KILL_GRACE)
        else:
            rc = _run_py(script_abs, args, timeout + KILL_GRACE)
    except subprocess.TimeoutExpired:
        print(f"  ⏱️ {label} TIMEOUT after {timeout}s")
        _stamp_freshness(step, ok=False)
        return False
    if rc == 0:
        print(f"  ✅ {label}")
        _stamp_freshness(step, ok=True)
        return True
    print(f"  ⚠️ {label} FAILED (exit {rc})")
    _stamp_freshness(step, ok=False)
    return False


def main() -> int:
    p = argparse.ArgumentParser(description="Declarative pipeline stage runner")
    p.add_argument("--cadence", required=True, choices=VALID_CADENCES)
    p.add_argument("--stage", choices=VALID_STAGES,
                   help="Run only this stage (default: all stages for the cadence)")
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--dry-run", action="store_true",
                   help="Print the ordered plan and exit without running anything")
    p.add_argument("--state-out",
                   help="Write .state.json here (via write_pipeline_state.decide_state)")
    args = p.parse_args()

    manifest = load_manifest(args.manifest)
    steps = select_steps(manifest, args.cadence, args.stage)

    print("=" * 60)
    print(f"run_stage: cadence={args.cadence} stage={args.stage or 'ALL'} "
          f"— {len(steps)} step(s){' [DRY RUN]' if args.dry_run else ''}")
    print("=" * 60)

    # ok/failed lists per stage, for the honest state writer.
    ok = {s: [] for s in VALID_STAGES}
    failed = {s: [] for s in VALID_STAGES}
    current = None
    for step in steps:
        if step["stage"] != current:
            current = step["stage"]
            print(f"\n── {current.upper()} ──")
        succeeded = run_step(step, args.dry_run)
        (ok if succeeded else failed)[step["stage"]].append(step["name"])

    if args.dry_run:
        return 0

    n_failed = sum(len(v) for v in failed.values())
    print("\n" + "=" * 60)
    for s in VALID_STAGES:
        if ok[s] or failed[s]:
            print(f"  {s}: {len(ok[s])} ok, {len(failed[s])} failed"
                  + (f"  [{', '.join(failed[s])}]" if failed[s] else ""))
    print("=" * 60)

    if args.state_out:
        try:
            sys.path.insert(0, HERE)
            from write_pipeline_state import decide_state
            from datetime import datetime, timezone
            state = decide_state(
                ok["bronze"], failed["bronze"], ok["silver"], failed["silver"],
                ok["gold"], failed["gold"], ok["consumption"], failed["consumption"],
            )
            payload = {
                "state": state,
                "cadence": args.cadence,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "ok": ok, "failed": failed,
            }
            with open(args.state_out, "w") as f:
                json.dump(payload, f, indent=2)
            print(f"state={state} written to {args.state_out}")
        except Exception as e:
            print(f"⚠️ could not write state file: {e}")

    return 1 if n_failed else 0


if __name__ == "__main__":
    sys.exit(main())
