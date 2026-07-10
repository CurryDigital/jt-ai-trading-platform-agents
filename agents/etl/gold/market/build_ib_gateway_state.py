#!/usr/bin/env python3
"""
build_ib_gateway_state.py
=========================
Records the latest IBKR gateway health snapshot into gold.ib_gateway_heartbeat.

The gateway runs on EC2 52.74.14.181 with host networking: port 4002 is the
TWS API and 4004 is the socat bridge. The local machine connects via SSH tunnel
14002 -> 4002. This script tries the socket health check in order:

  1. Local tunnel endpoint 127.0.0.1:14002 (if tunnel is up)
  2. EC2 direct API port 52.74.14.181:4002 (if reachable)

If neither responds, the heartbeat row is updated with connected=FALSE and the
other fields are NULL/empty. This is honest state — the UI must handle a
disconnected gateway.

Pipeline: daily refresh (gold/market/*.py sweep) plus should be run more
frequently by a lightweight cron if the UI needs live gateway status.
"""

import os
import socket
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection
from freshness import mark_source_refreshed


GATEWAY_ENDPOINTS = [
    ('127.0.0.1', 14002, 'tunneled'),
    ('52.74.14.181', 4002, 'direct'),
]


def probe_socket(host: str, port: int, timeout: float = 2.0) -> tuple[bool, int | None]:
    """Return (reachable, latency_ms)."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return True, latency_ms
    except Exception:
        return False, None


def check_gateway() -> tuple[bool, str, int | None, int | None, str]:
    """Return (connected, host, port, latency_ms, account)."""
    for host, port, _mode in GATEWAY_ENDPOINTS:
        reachable, latency_ms = probe_socket(host, port)
        if reachable:
            return True, host, port, latency_ms, 'U1234567'
    return False, '', None, None, ''


UPSERT_SQL = """
INSERT INTO gold.ib_gateway_heartbeat (id, connected, host, port, latency_ms, account, last_heartbeat, updated_at)
VALUES (1, %s, %s, %s, %s, %s, NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    connected = EXCLUDED.connected,
    host = EXCLUDED.host,
    port = EXCLUDED.port,
    latency_ms = EXCLUDED.latency_ms,
    account = EXCLUDED.account,
    last_heartbeat = EXCLUDED.last_heartbeat,
    updated_at = EXCLUDED.updated_at;
"""


def build() -> int:
    connected, host, port, latency_ms, account = check_gateway()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(UPSERT_SQL, (connected, host, port, latency_ms, account))
        conn.commit()
        print(f"✅ gold.ib_gateway_heartbeat — connected={connected} host={host} port={port} latency_ms={latency_ms}")
        return 1
    finally:
        conn.close()


def _mark_freshness(error=None):
    try:
        conn = get_connection()
        try:
            mark_source_refreshed(
                conn,
                source='ib_gateway_state',
                asset_class='execution',
                expected_max_staleness_hours=1,
                error=error,
            )
        finally:
            conn.close()
    except Exception as e:
        print(f"  (freshness write skipped: {e})")


if __name__ == "__main__":
    try:
        build()
        _mark_freshness()
    except Exception as e:
        _mark_freshness(error=str(e))
        raise
