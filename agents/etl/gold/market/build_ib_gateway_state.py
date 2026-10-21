#!/usr/bin/env python3
"""
build_ib_gateway_state.py
=========================
Records the latest IBKR gateway health snapshots into gold.ib_gateway_heartbeat,
one row per session (primary + uat).

The gateway runs on EC2 52.74.14.181 with host networking: port 4002 is the
TWS API and 4004 is the socat bridge. The local machine connects via SSH tunnel
14002 -> 4002. Each session tries its socket health checks in order:

  primary: 1. Local tunnel endpoint 127.0.0.1:14002 (if tunnel is up)
           2. EC2 direct API port 52.74.14.181:4002 (if reachable)
  uat:     IBKR_UAT_HOST / IBKR_UAT_PORT env (default: same paper endpoint
           until a dedicated UAT tunnel/port is provisioned)

If no endpoint responds, the session's heartbeat row is updated with
connected=FALSE and the other fields are NULL/empty. This is honest state —
the UI must handle a disconnected gateway.

connected=TRUE requires a FULL TWS API handshake (ib_insync connect +
managedAccounts()) with a dedicated probe clientId — a bare TCP connect is
not sufficient, because the gateway port accepts sockets even when no usable
session exists. The account column is populated from managedAccounts()
(e.g. DUP825942 for the paper gateway); when a probe cannot determine the
account, the last known value is preserved.

Paper sessions must NEVER probe live ports (4001/14001/7496); such endpoints
are refused before any socket is opened.

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


LIVE_PORTS = {4001, 14001, 7496}

# Dedicated clientIds for the probe sessions. The backend uses 1 (primary)
# and 2 (uat); the probe must never collide with those or it would steal /
# clash with the real sessions.
PROBE_CLIENT_IDS = {'primary': 90, 'uat': 91}

GATEWAY_SESSIONS = {
    # id=1: primary session (existing single gateway path)
    'primary': {
        'id': 1,
        'endpoints': [
            ('127.0.0.1', 14002, 'tunneled'),
            ('52.74.14.181', 4002, 'direct'),
        ],
    },
    # id=2: PAPER_UAT session — separate TWS/Gateway port+client.
    # Env-overridable; defaults to the same paper gateway endpoint until a
    # dedicated UAT tunnel/port is provisioned. Must NEVER point at live ports.
    'uat': {
        'id': 2,
        'endpoints': [
            (os.getenv('IBKR_UAT_HOST', '127.0.0.1'),
             int(os.getenv('IBKR_UAT_PORT', '14002')), 'uat'),
        ],
    },
}


def probe_socket(host: str, port: int, timeout: float = 2.0) -> tuple[bool, int | None]:
    """Return (reachable, latency_ms)."""
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency_ms = int((time.perf_counter() - t0) * 1000)
            return True, latency_ms
    except Exception:
        return False, None


def probe_api_session(host: str, port: int, client_id: int, timeout: float = 6.0) -> str | None:
    """Full TWS API handshake via ib_insync.

    Returns the first managed account id (e.g. 'DUP825942') when a real API
    session can be established, else None. A bare TCP connect is NOT enough —
    the gateway port accepts sockets even when no usable session exists,
    which is how the old writer kept reporting connected=TRUE with the
    placeholder account while every real session was down.
    """
    try:
        from ib_insync import IB
    except Exception as e:
        print(f"  ⚠️  ib_insync unavailable ({e}) — cannot verify API session")
        return None
    ib = IB()
    try:
        ib.connect(host, port, clientId=client_id, timeout=timeout)
        accounts = ib.managedAccounts()
        if accounts:
            return accounts[0]
        print(f"  ⚠️  API session established at {host}:{port} but managedAccounts() is empty")
        return None
    except Exception as e:
        print(f"  ⚠️  API handshake failed at {host}:{port} (clientId={client_id}): {type(e).__name__}: {e}")
        return None
    finally:
        try:
            ib.disconnect()
        except Exception:
            pass


def check_session(session_name: str, endpoints) -> tuple[bool, str, int | None, int | None, str | None]:
    """Return (connected, host, port, latency_ms, account).

    connected=TRUE only when a full TWS API handshake succeeds; account comes
    from managedAccounts(). account=None means 'unknown' — the upsert then
    preserves the last known value instead of blanking it.
    """
    client_id = PROBE_CLIENT_IDS.get(session_name, 90)
    for host, port, _mode in endpoints:
        if port in LIVE_PORTS:
            print(f"  ⚠️  refusing to probe live port {port} for a paper session — skipping")
            continue
        reachable, latency_ms = probe_socket(host, port)
        if not reachable:
            continue
        account = probe_api_session(host, port, client_id)
        if account:
            return True, host, port, latency_ms, account
        # Socket reachable but no real API session — honest disconnected state.
        return False, host, port, latency_ms, None
    return False, '', None, None, None


UPSERT_SQL = """
INSERT INTO gold.ib_gateway_heartbeat (id, session, connected, host, port, latency_ms, account, last_heartbeat, updated_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
ON CONFLICT (id) DO UPDATE SET
    session = EXCLUDED.session,
    connected = EXCLUDED.connected,
    host = EXCLUDED.host,
    port = EXCLUDED.port,
    latency_ms = EXCLUDED.latency_ms,
    -- Preserve the last known account when this probe could not determine it
    -- (disconnected / handshake failure) instead of blanking the column.
    account = COALESCE(EXCLUDED.account, gold.ib_gateway_heartbeat.account),
    last_heartbeat = EXCLUDED.last_heartbeat,
    updated_at = EXCLUDED.updated_at;
"""


def build() -> int:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for session_name, cfg in GATEWAY_SESSIONS.items():
                connected, host, port, latency_ms, account = check_session(session_name, cfg['endpoints'])
                cur.execute(UPSERT_SQL, (cfg['id'], session_name, connected, host, port, latency_ms, account))
                print(f"✅ gold.ib_gateway_heartbeat[{session_name}] — connected={connected} host={host} port={port} latency_ms={latency_ms} account={account}")
        conn.commit()
        return len(GATEWAY_SESSIONS)
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
