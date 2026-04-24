#!/usr/bin/env python3
"""
Hub Agent — OpenClaw Quant Pipeline
TYPE: Isolated — always-on

The Hub is the sole event router. It:
  1. Polls v_pending_events every POLL_INTERVAL seconds
  2. For each unrouted event, looks up routing_rules by (domain, event_type)
  3. Calls sessions_send to wake each target agent
  4. Records itself in event_processing as 'hub_router' so the event
     is not re-dispatched on the next cycle

The Hub never modifies payloads, never emits domain events,
and never calls agents directly — only via sessions_send.
Routing table lives in the DB (routing_rules) and is mirrored
in the static ROUTING_TABLE in hub/router.py.

Soul: Silent and fast. Terse structured logs only.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.router import get_hub

from agents.shared.constants import SCHEMA, QUANT_DOMAIN, PLATFORM_DOMAIN
AGENT_ID     = 'qr_hub'   # name recorded in event_processing for dedup
POLL_INTERVAL = 2             # seconds between polling cycles


# ─────────────────────────────────────────────────────────────────────────────
# ROUTING
# ─────────────────────────────────────────────────────────────────────────────

def get_pending_events(hub):
    """
    Pull all events not yet routed by the Hub.
    Uses v_pending_events which filters on event_processing.agent_name = 'qr_hub'.
    """
    conn = hub._get_conn()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SELECT * FROM {SCHEMA}.v_pending_events LIMIT 100")
            return cur.fetchall()
    finally:
        conn.close()


def mark_routed(hub, event_id):
    """
    Record hub_router in event_processing so this event is not re-dispatched.
    Uses ON CONFLICT DO NOTHING for idempotency.
    """
    conn = hub._get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                INSERT INTO {SCHEMA}.event_processing (event_id, agent_name)
                VALUES (%s, %s)
                ON CONFLICT (event_id, agent_name) DO NOTHING
            """, (str(event_id), AGENT_ID))
        conn.commit()
    finally:
        conn.close()


def route_event(hub, event):
    """
    Route a single event to its target agents via sessions_send.

    Steps:
      1. Look up target agents from ROUTING_TABLE (static, fast)
         with DB routing_rules as fallback for dynamic overrides.
      2. Call _dispatch_to_agent for each target — this calls sessions_send
         (or falls back to .notification_queue if outside agent session).
      3. Mark event as routed in event_processing.

    Returns count of agents dispatched to.
    """
    event_id   = event['event_id']
    event_type = event['event_type']
    domain     = event['domain'] or 'quant'
    strategy_id = event['strategy_id']

    target_agents = hub._get_routing_targets(event_type, domain)

    if not target_agents:
        # No routing rule — log and mark routed so we don't retry forever.
        log(f"NO_ROUTE event_id={event_id} type={event_type} domain={domain}")
        mark_routed(hub, event_id)
        return 0

    dispatched = 0
    for agent_name in target_agents:
        result = hub._dispatch_to_agent(
            agent_name=agent_name,
            event_id=str(event_id),
            event_type=event_type,
            strategy_id=strategy_id,
            domain=domain,
        )
        if result:
            dispatched += 1

    mark_routed(hub, event_id)

    log(
        f"ROUTED event_id={event_id} "
        f"type={event_type} "
        f"domain={domain} "
        f"targets={target_agents}"
    )
    return dispatched


# ─────────────────────────────────────────────────────────────────────────────
# POLL CYCLE
# ─────────────────────────────────────────────────────────────────────────────

def run_hub_cycle(hub):
    """One routing cycle — drain all pending events."""
    try:
        pending = get_pending_events(hub)

        if not pending:
            return  # nothing to do; stay silent per soul

        total_dispatched = 0
        for event in pending:
            total_dispatched += route_event(hub, event)

        log(f"CYCLE events={len(pending)} dispatched={total_dispatched}")

    except Exception as e:
        log(f"ERROR cycle failed: {e}")


# ─────────────────────────────────────────────────────────────────────────────
# SOUL: terse structured logs only
# ─────────────────────────────────────────────────────────────────────────────

def log(message):
    """Hub is silent and fast. Terse structured log entries only."""
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
    print(f"[{ts}] Hub: {message}", flush=True)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN — always-on loop
# ─────────────────────────────────────────────────────────────────────────────

def main():
    log("start poll_interval=2s")
    hub = get_hub()

    while True:
        run_hub_cycle(hub)
        time.sleep(POLL_INTERVAL)


if __name__ == '__main__':
    main()
