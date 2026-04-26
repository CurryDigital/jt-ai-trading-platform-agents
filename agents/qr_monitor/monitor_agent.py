#!/usr/bin/env python3
"""
Monitor Agent (Hub-based) - OpenClaw Quant Pipeline
Isolated agent: always-on watchdog. Uses Hub for DB connections.

Note: Monitor does NOT extend Agent because it has no trigger event.
It runs as a standalone polling process.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.router import get_hub

from agents.shared.constants import (
    SCHEMA, AGENT_MONITOR as AGENT_ID, TIMEOUT_THRESHOLDS,
    GOLD_LAYER_LOCK_TIMEOUT_HOURS,
)


def get_in_progress_work(hub):
    """
    Scan event_processing for stalled work.
    Uses v_monitor_overview which joins event_processing + events.
    """
    conn = hub._get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    event_id,
                    agent_id,
                    event_type,
                    experiment_id,
                    workflow_id,
                    elapsed_minutes
                FROM {SCHEMA}.v_monitor_overview
                WHERE elapsed_minutes > 0
                ORDER BY elapsed_minutes DESC
            """)
            return cur.fetchall()
    finally:
        conn.close()

def check_workflow_stuck_count(hub, workflow_id):
    """Check how many times this workflow has been flagged as stuck."""
    conn = hub._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) as stuck_count
                FROM {SCHEMA}.events
                WHERE event_type = 'workflow.stuck'
                  AND payload_json->>'workflow_id' = %s
            """, (workflow_id,))
            result = cur.fetchone()
            return result[0] if result else 0
    finally:
        conn.close()

def has_been_requeued(hub, event_id):
    """Check if this event has already been re-queued once."""
    conn = hub._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT COUNT(*) as requeue_count
                FROM {SCHEMA}.workflow_events
                WHERE data->>'event_id' = %s
                  AND event_type = 'monitor_requeue'
            """, (str(event_id),))
            result = cur.fetchone()
            return (result[0] if result else 0) > 0
    finally:
        conn.close()

def emit_workflow_stuck(hub, event_id, workflow_id, stuck_at_event, agent_name, elapsed_minutes, requeued):
    """Emit workflow.stuck event."""
    conn = hub._get_conn()
    try:
        payload = {
            'workflow_id': workflow_id,
            'stuck_at_event': stuck_at_event,
            'agent_name': agent_name,
            'elapsed_seconds': int(elapsed_minutes * 60),
            'requeued': requeued,
            'requeue_count': 1 if requeued else 0
        }

        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {SCHEMA}.events
                    (event_type, payload_json, domain, source_agent, strategy_id)
                VALUES
                    ('workflow.stuck', %s, 'quant', %s, %s)
            """, (json.dumps(payload), AGENT_ID, workflow_id))

            cur.execute(f"""
                INSERT INTO {SCHEMA}.workflow_events
                    (event_type, agent, from_status, to_status, data)
                VALUES
                    ('workflow.stuck', %s, 'stuck', 'escalated', %s)
            """, (AGENT_ID, json.dumps({'target_event_id': str(event_id), 'workflow_id': workflow_id})))

        conn.commit()
        log(f"Emitted workflow.stuck for workflow_id {workflow_id} at {stuck_at_event}")
    finally:
        conn.close()

def requeue_event(hub, event_id):
    """Re-queue the stuck event by removing its event_processing entry."""
    conn = hub._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                DELETE FROM {SCHEMA}.event_processing
                WHERE event_id = %s
            """, (str(event_id),))

            cur.execute(f"""
                INSERT INTO {SCHEMA}.workflow_events
                    (event_type, agent, from_status, to_status, data)
                VALUES
                    ('monitor_requeue', %s, 'in_progress', 'requeued', %s)
            """, (AGENT_ID, json.dumps({'event_id': str(event_id)})))

        conn.commit()
        log(f"Re-queued event {event_id}")
    finally:
        conn.close()

def mark_failed(hub, workflow_id, reason):
    """Escalate to failed after 2 workflow.stuck events."""
    conn = hub._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {SCHEMA}.workflow_events
                    (event_type, agent, from_status, to_status, strategy_id, data)
                VALUES
                    ('workflow_failed', %s, 'stuck', 'failed', NULL, %s)
            """, (AGENT_ID, json.dumps({'workflow_id': workflow_id, 'reason': reason})))

            cur.execute(f"""
                UPDATE {SCHEMA}.strategy_workflow
                SET status = 'failed', updated_at = now()
                WHERE strategy_id = %s
            """, (workflow_id,))

        conn.commit()
        log(f"Workflow {workflow_id} marked as FAILED after 2 stuck events")
    finally:
        conn.close()

def log(message):
    """Calm and factual. Never panics."""
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{timestamp}] Monitor: {message}")

def get_orphaned_events(hub):
    """
    M5 FIX: Find pipeline events that have NO event_processing rows at all,
    meaning the Hub never routed them. These are invisible to v_monitor_overview
    (which only shows events that HAVE been processed).
    Only checks event types with known timeouts.
    """
    conn = hub._get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"""
                SELECT
                    e.id AS event_id,
                    e.event_type,
                    e.strategy_id AS workflow_id,
                    e.domain,
                    EXTRACT(epoch FROM now() - e.created_at) / 60 AS age_minutes
                FROM {SCHEMA}.events e
                LEFT JOIN {SCHEMA}.event_processing ep ON e.id = ep.event_id
                WHERE e.domain = 'quant'
                  AND e.event_type IN ('experiment.started', 'dataset.ready',
                                       'backtest.completed', 'risk.evaluated',
                                       'qa.validated')
                  AND ep.event_id IS NULL
                  AND e.created_at < NOW() - INTERVAL '5 minutes'
                ORDER BY e.created_at ASC
                LIMIT 50
            """)
            return cur.fetchall()
    finally:
        conn.close()

def clear_stale_gold_lock(hub, max_lock_hours: int = GOLD_LAYER_LOCK_TIMEOUT_HOURS):
    """
    Break wedged ETL locks. The data validator skips events while the gold layer
    is 'locked' without marking them processed, so a crashed ETL can stall every
    experiment indefinitely. This calls the SQL helper installed by migration_006
    to flip stale locks back to 'stale' so the next ETL cycle re-runs cleanly.
    """
    conn = hub._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {SCHEMA}.clear_stale_gold_lock(%s)",
                (max_lock_hours,)
            )
            cleared = cur.fetchone()[0]
        conn.commit()
        if cleared:
            log(f"Cleared {cleared} stale gold-layer lock(s) older than {max_lock_hours}h")
    except Exception as e:
        log(f"clear_stale_gold_lock failed: {e}")
    finally:
        conn.close()


def run_monitor_cycle(hub):
    """One monitoring cycle — check stalled and orphaned events."""
    try:
        # Check 0: auto-unlock gold layer if ETL has been wedged > timeout.
        clear_stale_gold_lock(hub)

        # Check 1: events processed but timed out (original logic)
        in_progress = get_in_progress_work(hub)

        for work in in_progress:
            event_type = work['event_type']
            elapsed = work['elapsed_minutes']
            event_id = work['event_id']
            workflow_id = work['workflow_id']
            agent_id = work['agent_id']

            if event_type not in TIMEOUT_THRESHOLDS:
                continue

            threshold = TIMEOUT_THRESHOLDS[event_type]

            if elapsed < threshold:
                continue

            log(f"workflow_id {workflow_id} stuck at {event_type} for {int(elapsed)} minutes. Agent: {agent_id}.")

            stuck_count = check_workflow_stuck_count(hub, workflow_id)

            if stuck_count >= 2:
                mark_failed(hub, workflow_id, f"Exceeded 2 stuck events for {event_type}")
                continue

            already_requeued = has_been_requeued(hub, event_id)

            if already_requeued:
                emit_workflow_stuck(hub, event_id, workflow_id, event_type, agent_id, elapsed, requeued=False)
                log(f"Re-queue already attempted. Emitting workflow.stuck for escalation.")
            else:
                requeue_event(hub, event_id)
                emit_workflow_stuck(hub, event_id, workflow_id, event_type, agent_id, elapsed, requeued=True)
                log(f"Re-queuing once.")

        # Check 2: orphaned events never routed by Hub (M5 fix)
        orphaned = get_orphaned_events(hub)
        if orphaned:
            log(f"Found {len(orphaned)} orphaned events (never routed by Hub)")
            for orph in orphaned:
                age = orph['age_minutes']
                event_type = orph['event_type']
                threshold = TIMEOUT_THRESHOLDS.get(event_type, 15)
                if age > threshold:
                    log(f"ORPHAN: event {orph['event_id']} type={event_type} "
                        f"workflow={orph['workflow_id']} age={int(age)}m — never routed")

    except Exception as e:
        log(f"Error in monitor cycle: {str(e)}")

def main():
    """Always-on loop."""
    log("Monitor agent started. Watching for stalled workflows.")

    hub = get_hub()

    while True:
        run_monitor_cycle(hub)
        time.sleep(30)

if __name__ == '__main__':
    main()
