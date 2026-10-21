#!/usr/bin/env python3
"""
Daily Signal Runner
===================
Loads the strategy registry, instantiates every enabled strategy, calls
run() + save(), and prints a summary table.

2026-06-22: refactored to read strategies/registry.json instead of
hardcoding `from strategies.experimental.strategy_01 import Strategy01` for
20 classes. Adding a new strategy now requires no edits to this file.

To onboard a new strategy:
  python3 strategies/register_strategy.py --id 21 --name "..." --regime TREND --asset-class equity
Then implement strategies/experimental/strategy_21.py::Strategy21 and flip
`enabled: true` in registry.json. The next cron picks it up.
"""

import json
import os
import sys
from datetime import datetime, timezone

# Signal-agent layout (post 2026-06-22 split):
#   agents/signals/strategies/run_signals.py  ← this file
#   agents/etl/shared/scripts/db.py            ← canonical DB pool (cross-agent dep)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, '..'))
ETL_SHARED = os.path.normpath(os.path.join(SIGNALS_ROOT, '..', 'etl', 'shared', 'scripts'))
sys.path.insert(0, SIGNALS_ROOT)
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from strategies.registry_loader import (
    load_enabled_strategies, import_strategy_class, RegistryError,
)
# regime_rules is already a hard per-strategy dependency (is_active_today
# imports it), but guard the runner-level import so a regime_rules failure
# degrades the audit trail instead of crashing the runner before any
# strategy loads. map_source 'import_failed' is outside the spec's
# registry|legacy_fallback vocabulary and only appears when the run itself
# is already broken.
try:
    from regime.regime_rules import STRATEGY_MAP, STRATEGY_MAP_SOURCE
except Exception as _regime_import_err:
    print(f"WARNING: regime_rules import failed ({_regime_import_err}); "
          f"audit map_source='import_failed'", file=sys.stderr)
    STRATEGY_MAP = {}
    STRATEGY_MAP_SOURCE = 'import_failed'

# ── Regime-gate decision audit (2026-10-07, kanban t_22ef1dff) ───────────────
# Spec: qr_research deriv_equity_enrichment_v1/REGIME_GATE_SNAPSHOT_SPEC.md.
# gold.regime_label is rewritten nightly, so without this log the gate decision
# for any past day is unreproducible. One row per strategy per run goes to
# gold.regime_gate_decision_log (append-only, ON CONFLICT DO NOTHING). A failed
# audit write must NEVER fail the signal run: warn + agent_events, continue.
# The audit uses its OWN connection so a failed INSERT cannot abort the shared
# strategy connection's transaction (which would break later strategies).

def _read_regime_label_row(cur):
    """Read the latest gold.regime_label row the gate will see, full row."""
    cur.execute("""
        SELECT date, regime, hmm_label, override_used, confidence, severity,
               computed_at
        FROM gold.regime_label
        WHERE date = (SELECT MAX(date) FROM gold.regime_label)
    """)
    return cur.fetchone()


def _label_row_json(label):
    if label is None:
        return None
    return json.dumps({
        'date': str(label[0]),
        'regime': label[1],
        'hmm_label': label[2],
        'override_used': bool(label[3]) if label[3] is not None else None,
        'confidence': float(label[4]) if label[4] is not None else None,
        'severity': int(label[5]) if label[5] is not None else None,
        'computed_at': str(label[6]),
    })


def _emit_audit_failure(run_id, strategy_id, err):
    """WARNING to the pipeline log AND a gold.agent_events row (best effort)."""
    print(f"  WARNING: regime-gate audit write failed for strategy "
          f"{strategy_id} (run {run_id}): {err}", file=sys.stderr)
    payload = json.dumps({
        'run_id': run_id,
        'strategy_id': strategy_id,
        'error': str(err),
    })
    try:
        c = get_connection()
        try:
            acur = c.cursor()
            acur.execute("""
                INSERT INTO gold.agent_events
                  (event_type, strategy_id, domain, agent_name, payload_json,
                   status, created_at, payload)
                VALUES ('regime_gate_log_write_failed', %s, 'signals',
                        'run_signals', %s::jsonb, 'error', NOW(), %s::jsonb)
            """, (str(strategy_id), payload, payload))
            c.commit()
        finally:
            c.close()
    except Exception as e2:
        print(f"  WARNING: agent_events audit-failure write also failed: {e2}",
              file=sys.stderr)


def _log_gate_decision(audit_conn, run_id, result, label):
    """INSERT one append-only row into gold.regime_gate_decision_log.
    Never raises: failures roll back the audit conn, warn, and emit an
    agent_events row. Returns nothing."""
    strategy_id = result['strategy_id']
    try:
        regime_seen = label[1] if label else None
        active = STRATEGY_MAP.get(regime_seen, []) if regime_seen else []
        active_ids_json = json.dumps({regime_seen: active} if regime_seen else {})
        acur = audit_conn.cursor()
        acur.execute("""
            INSERT INTO gold.regime_gate_decision_log
                (run_id, strategy_id, strategy_name, label_date, regime,
                 confidence, severity, override_used, map_source, active_ids,
                 is_active, label_row)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb)
            ON CONFLICT (run_id, strategy_id) DO NOTHING
        """, (
            run_id,
            strategy_id,
            result['name'],
            label[0] if label else None,
            regime_seen,
            float(label[4]) if label and label[4] is not None else None,
            int(label[5]) if label and label[5] is not None else None,
            bool(label[3]) if label and label[3] is not None else None,
            STRATEGY_MAP_SOURCE,
            active_ids_json,
            bool(result['active']),
            _label_row_json(label),
        ))
        audit_conn.commit()
    except Exception as e:
        try:
            audit_conn.rollback()
        except Exception:
            pass
        _emit_audit_failure(run_id, strategy_id, e)


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
    # run_id joins DB rows in gold.regime_gate_decision_log to this run's
    # pipeline_b log (printed here, in the log header).
    run_id = f"signalrun_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}_{os.getpid()}"
    print(f"Signal run id: {run_id}")

    try:
        enabled = load_enabled_strategies()
    except RegistryError as e:
        print(f"FATAL: strategy registry invalid: {e}", file=sys.stderr)
        return 2

    if not enabled:
        print("⚠️  No enabled strategies in registry.json — nothing to do.", file=sys.stderr)
        return 0

    conn = get_connection()

    # Read the regime row the gate will see (full row, for the audit log).
    cur = conn.cursor()
    label = _read_regime_label_row(cur)
    regime = label[1] if label else 'UNKNOWN'

    # Dedicated audit connection: a failed audit INSERT must not abort the
    # shared strategy connection's transaction.
    try:
        audit_conn = get_connection()
    except Exception as e:
        print(f"  WARNING: no audit connection ({e}) — regime-gate decision "
              f"log disabled for run {run_id}", file=sys.stderr)
        audit_conn = None
        _emit_audit_failure(run_id, None, e)

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
            if audit_conn is not None:
                _log_gate_decision(audit_conn, run_id, result, label)
        except Exception as e:
            print(f"  ERROR strategy {entry.id} ({entry.name}): {e}", file=sys.stderr)
            n_errors += 1

    if audit_conn is not None:
        try:
            audit_conn.close()
        except Exception:
            pass

    print_summary(results, regime)
    conn.close()
    print(f"\n✅ Signal run complete — {len(results)}/{len(enabled)} strategies processed "
          f"({n_errors} errors) [run_id={run_id}]")
    return 0 if n_errors == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
