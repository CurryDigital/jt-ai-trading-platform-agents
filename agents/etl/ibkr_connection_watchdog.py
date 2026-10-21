#!/usr/bin/env python3
"""
IBKR connection watchdog using ib_insync (Hermes venv Python 3.11).
Probes the TWS API with a full handshake and managedAccounts response.
Restarts SSH tunnel on failure with a 15-minute cooldown.
Logs results to Postgres.

Runs every 5 minutes via cron.
"""
import asyncio
import datetime
import logging
import os
import random
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import psycopg2

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s HKT [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ibkr_watchdog")

# HKT converter
HKT_OFFSET = datetime.timedelta(hours=8)
old_converter = logging.Formatter.converter
def hkt_converter(*args):
    seconds = args[0] if len(args) == 1 else args[1]
    return (datetime.datetime.fromtimestamp(seconds, datetime.timezone.utc) + HKT_OFFSET).timetuple()
logging.Formatter.converter = hkt_converter

def _load_env():
    env_path = Path.home() / '.env'
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if '=' in line and not line.startswith('#'):
                k, v = line.split('=', 1)
                os.environ.setdefault(k, v)

_load_env()

LOCAL_HOST = os.environ.get("IBKR_LOCAL_HOST", "127.0.0.1")
LOCAL_PORT = int(os.environ.get("IBKR_LOCAL_PORT", "14002"))
GATEWAY_HOST = os.environ.get("IBKR_GATEWAY_HOST", "52.74.14.181")
GATEWAY_USER = os.environ.get("IBKR_GATEWAY_USER", "ubuntu")
GATEWAY_KEY = os.environ.get("IBKR_GATEWAY_KEY", "/home/ubuntu/.ssh/ibkr_ec2.pem")
GATEWAY_CONTAINER = os.environ.get("IBKR_GATEWAY_CONTAINER", "algo-trader-ib-gateway-1")

TUNNEL_SERVICE = os.environ.get("IBKR_TUNNEL_SERVICE", "ibkr-tunnel.service")
RESTART_COOLDOWN_SECONDS = int(os.environ.get("IBKR_WATCHDOG_RESTART_COOLDOWN_SECONDS", "900"))  # 15 min

# Gateway container recovery (t_94a03f84): when the probe keeps failing because the
# gateway itself is LOGGED_OUT (e.g. IBKR login lockout that IBC never retries),
# restarting the ssh tunnel is useless — the container must be restarted instead.
CONTAINER_RESTART_COOLDOWN_SECONDS = int(os.environ.get("IBKR_WATCHDOG_CONTAINER_RESTART_COOLDOWN_SECONDS", "3600"))  # 1h
FAIL_THRESHOLD = int(os.environ.get("IBKR_WATCHDOG_FAIL_THRESHOLD", "3"))  # consecutive failed probes before container action
GATEWAY_LOG_WINDOW = os.environ.get("IBKR_GATEWAY_LOG_WINDOW", "45m")  # docker logs --since window for login-state classification
CONTAINER_LOGIN_WAIT_SECONDS = int(os.environ.get("IBKR_WATCHDOG_CONTAINER_LOGIN_WAIT_SECONDS", "75"))

STATE_DIR = Path.home() / ".hermes" / "profiles" / "qr_etl" / "var"
FAIL_COUNT_STATE = STATE_DIR / "ibkr_watchdog_fail_count.state"
CONTAINER_RESTART_STATE = STATE_DIR / "ibkr_watchdog_container_restart.state"

# docker log lines that prove the gateway ended up LOGGED_OUT (IBC gives up after these)
LOGGED_OUT_MARKERS = (
    "Too many failed login attempts",
    "LoginState is LOGGED_OUT",
    "Login has not completed",
    "Authorization failed",
)
LOGIN_OK_MARKER = "Login has completed"

@dataclass
class ProbeResult:
    ok: bool
    stage: str
    error: Optional[str] = None
    duration_ms: float = 0.0
    server_version: Optional[int] = None
    managed_accounts: Optional[str] = None


def now_hkt() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc) + HKT_OFFSET


def normalize_db_name(name: Optional[str]) -> str:
    if name and name.lower() == "airtrading":
        return "aitrading"
    return name or "aitrading"


PG_HOST = os.environ.get("IBKR_PG_HOST",
                        os.environ.get("OPENCLAW_DB_HOST",
                        os.environ.get("AIRTRADING_DB_HOST", "openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com")))
PG_DB = normalize_db_name(os.environ.get("IBKR_PG_DB",
                        os.environ.get("OPENCLAW_DB_NAME",
                        os.environ.get("AIRTRADING_DB_NAME"))))
PG_USER = os.environ.get("IBKR_PG_USER",
                          os.environ.get("OPENCLAW_DB_USER",
                          os.environ.get("AIRTRADING_DB_USER", "openclaw_user")))
PG_PASSWORD = os.environ.get("IBKR_PG_PASSWORD",
                             os.environ.get("OPENCLAW_DB_PASSWORD",
                             os.environ.get("AIRTRADING_DB_PASSWORD")))
PG_SCHEMA = os.environ.get("IBKR_PG_SCHEMA", "shared")


def tunnel_listening() -> bool:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect((LOCAL_HOST, LOCAL_PORT))
        s.close()
        return True
    except Exception:
        return False


def restart_tunnel() -> bool:
    """Restart the systemd-managed SSH tunnel."""
    logger.warning("Restarting systemd tunnel service %s", TUNNEL_SERVICE)
    proc = subprocess.run(
        ["sudo", "systemctl", "restart", TUNNEL_SERVICE],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        logger.error("systemctl restart failed: %s", proc.stderr)
        return False
    # Wait for port to bind
    for _ in range(20):
        time.sleep(1)
        if tunnel_listening():
            logger.info("Tunnel port %s:%s listening after restart", LOCAL_HOST, LOCAL_PORT)
            return True
    logger.error("Tunnel port did not bind after restart")
    return False


def cooldown_elapsed(state_path: Path, cooldown_seconds: int = RESTART_COOLDOWN_SECONDS) -> bool:
    if not state_path.exists():
        return True
    try:
        last = float(state_path.read_text().strip())
        return time.time() - last >= cooldown_seconds
    except Exception:
        return True


def touch_cooldown(state_path: Path):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(str(time.time()))


def read_fail_count() -> int:
    try:
        return int(FAIL_COUNT_STATE.read_text().strip())
    except Exception:
        return 0


def write_fail_count(n: int):
    FAIL_COUNT_STATE.parent.mkdir(parents=True, exist_ok=True)
    FAIL_COUNT_STATE.write_text(str(n))


def run_ssh(remote_cmd: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Run a command on the gateway host. BatchMode: fail fast, never prompt."""
    return subprocess.run(
        [
            "ssh", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=15", "-i", GATEWAY_KEY,
            f"{GATEWAY_USER}@{GATEWAY_HOST}", remote_cmd,
        ],
        capture_output=True, text=True, timeout=timeout,
    )


def gateway_login_state() -> str:
    """
    Classify the gateway's most recent login event from container logs.
    Returns 'healthy' (last event was a completed login), 'logged_out'
    (IBC gave up after a lockout/auth failure), or 'unknown'.
    """
    grep_pat = "|".join([LOGIN_OK_MARKER] + list(LOGGED_OUT_MARKERS))
    try:
        proc = run_ssh(
            f"docker logs --since {GATEWAY_LOG_WINDOW} {GATEWAY_CONTAINER} 2>&1 "
            f"| grep -E '{grep_pat}' | tail -1",
            timeout=60,
        )
    except Exception as e:
        logger.error("gateway_login_state ssh failed: %s", e)
        return "unknown"
    line = (proc.stdout or "").strip()
    if proc.returncode != 0 and not line:
        logger.error("gateway_login_state: no matching log lines (rc=%s)", proc.returncode)
        return "unknown"
    logger.info("gateway last login event: %s", line[-200:])
    if LOGIN_OK_MARKER in line:
        return "healthy"
    if any(m in line for m in LOGGED_OUT_MARKERS):
        return "logged_out"
    return "unknown"


def restart_gateway_container() -> bool:
    """Restart the gateway container on the remote host and wait for IBC to log in."""
    logger.warning("Restarting gateway container %s on %s", GATEWAY_CONTAINER, GATEWAY_HOST)
    try:
        proc = run_ssh(f"docker restart {GATEWAY_CONTAINER}", timeout=120)
    except Exception as e:
        logger.error("container restart ssh failed: %s", e)
        return False
    if proc.returncode != 0:
        logger.error("container restart failed: %s", proc.stderr)
        return False
    logger.info("container restarted; waiting %ss for IBC login", CONTAINER_LOGIN_WAIT_SECONDS)
    time.sleep(CONTAINER_LOGIN_WAIT_SECONDS)
    return True


async def probe_insync() -> ProbeResult:
    """Full ib_insync handshake; returns managedAccounts on success."""
    # Import inside function so the script is importable in environments without ib_insync
    from ib_insync import IB

    t0 = time.time()
    client_id = random.randint(10000, 65535)
    ib = IB()
    try:
        await ib.connectAsync(LOCAL_HOST, LOCAL_PORT, clientId=client_id, timeout=15)
        duration = (time.time() - t0) * 1000
        accts = ib.managedAccounts()
        sv = ib.client.serverVersion() if ib.client else None
        ib.disconnect()
        return ProbeResult(
            ok=True,
            stage="api",
            duration_ms=duration,
            server_version=sv,
            managed_accounts=",".join(accts) if accts else None,
        )
    except Exception as e:
        try:
            ib.disconnect()
        except Exception:
            pass
        return ProbeResult(ok=False, stage="handshake", error=str(e))


# Backend session recovery: the gateway probe only tests the tunnel path. The
# backend's own TWS sessions (clientId 1 = main, 2 = UAT) drop on every gateway
# nightly reset and only reconnect when someone hits the connect endpoint
# (lazy reconnect in ib_service.py). Close that gap: when the gateway probe is
# OK but a backend session reports disconnected, POST the connect endpoint.
BACKEND_BASE_URL = os.environ.get("IBKR_BACKEND_BASE_URL", "http://127.0.0.1:8000")
BACKEND_RECONNECT_COOLDOWN_SECONDS = int(os.environ.get("IBKR_WATCHDOG_BACKEND_RECONNECT_COOLDOWN_SECONDS", "300"))

def _backend_reconnect_state(label: str) -> Path:
    # Per-session cooldown: when BOTH sessions drop on a gateway reset, a single
    # shared state file let main reconnect and then suppressed UAT for a full
    # extra cooldown cycle (observed 2026-09-05: UAT down ~20 min every morning).
    return STATE_DIR / f"ibkr_watchdog_backend_reconnect_{label}.state"

def ensure_backend_sessions() -> str:
    """Re-trigger backend /api/ib/tws{,/uat}/connect when a session is down."""
    import json
    import urllib.request

    actions = []
    for label, status_url, connect_url in (
        ("main", f"{BACKEND_BASE_URL}/api/ib/tws/status", f"{BACKEND_BASE_URL}/api/ib/tws/connect"),
        ("uat", f"{BACKEND_BASE_URL}/api/ib/tws/uat/status", f"{BACKEND_BASE_URL}/api/ib/tws/uat/connect"),
    ):
        state_path = _backend_reconnect_state(label)
        try:
            with urllib.request.urlopen(status_url, timeout=10) as resp:
                status = json.loads(resp.read().decode())
        except Exception as e:
            logger.warning("backend %s status check failed: %s", label, e)
            actions.append(f"{label}_status_unreachable")
            continue
        if status.get("is_connected"):
            continue
        if not cooldown_elapsed(state_path, BACKEND_RECONNECT_COOLDOWN_SECONDS):
            logger.warning("backend %s disconnected but reconnect cooldown active", label)
            actions.append(f"{label}_reconnect_cooldown")
            continue
        logger.warning("backend %s session disconnected; POST %s", label, connect_url)
        try:
            req = urllib.request.Request(connect_url, method="POST")
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode())
            touch_cooldown(state_path)
            logger.info("backend %s reconnect result: %s", label, body)
            actions.append(f"reconnected_backend_{label}")
        except Exception as e:
            logger.error("backend %s reconnect failed: %s", label, e)
            actions.append(f"reconnect_backend_{label}_failed")
    return "+".join(actions) if actions else ""

def log_to_postgres(result: ProbeResult, action_taken: str) -> None:
    if not PG_PASSWORD:
        logger.warning("PG_PASSWORD not set; skipping DB logging")
        return
    try:
        conn = psycopg2.connect(
            host=PG_HOST, dbname=PG_DB, user=PG_USER, password=PG_PASSWORD,
            connect_timeout=10,
        )
        cur = conn.cursor()
        cur.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PG_SCHEMA}.ibkr_connection_log (
                id SERIAL PRIMARY KEY,
                checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                ok BOOLEAN NOT NULL,
                stage TEXT NOT NULL,
                error TEXT,
                duration_ms NUMERIC,
                server_version INT,
                action_taken TEXT,
                local_host TEXT,
                local_port INT,
                managed_accounts TEXT
            );
            """
        )
        cur.execute(
            f"""
            INSERT INTO {PG_SCHEMA}.ibkr_connection_log
                (checked_at, ok, stage, error, duration_ms, server_version, action_taken, local_host, local_port, managed_accounts)
            VALUES (NOW(), %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (result.ok, result.stage, result.error, result.duration_ms, result.server_version, action_taken, LOCAL_HOST, LOCAL_PORT, result.managed_accounts),
        )
        conn.commit()
        cur.close()
        conn.close()
        logger.info("Logged to %s.ibkr_connection_log", PG_SCHEMA)
    except Exception as e:
        logger.error("Failed to log to postgres: %s", e)


def main() -> int:
    tunnel_state = STATE_DIR / "ibkr_watchdog_restart.state"
    action_taken = "none"

    result = asyncio.run(probe_insync())

    if result.ok:
        write_fail_count(0)
    else:
        logger.warning("Probe failed at stage %s: %s", result.stage, result.error)
        fail_count = read_fail_count() + 1
        write_fail_count(fail_count)
        logger.warning("Consecutive probe failures: %s (threshold %s)", fail_count, FAIL_THRESHOLD)

        # Step 1: tunnel restart (cheap, fixes local forwarding issues)
        if cooldown_elapsed(tunnel_state):
            if restart_tunnel():
                action_taken = "restarted_tunnel"
                touch_cooldown(tunnel_state)
                result = asyncio.run(probe_insync())
                if result.ok:
                    write_fail_count(0)
            else:
                action_taken = "tunnel_restart_failed"
        else:
            logger.warning("Tunnel restart cooldown active; not restarting tunnel")
            action_taken = "cooldown_active"

        # Step 2: if the probe STILL fails after N consecutive runs, check whether the
        # gateway itself is LOGGED_OUT (IBC never retries a lockout) and restart the
        # container instead of the tunnel. Gated on remote log evidence + 1h cooldown
        # so we never hammer IBKR login during their nightly reset window.
        if not result.ok and fail_count >= FAIL_THRESHOLD:
            if not cooldown_elapsed(CONTAINER_RESTART_STATE, CONTAINER_RESTART_COOLDOWN_SECONDS):
                logger.warning("Container restart cooldown active; skipping gateway restart")
                action_taken += "+container_cooldown_active"
            else:
                state = gateway_login_state()
                if state == "logged_out":
                    if restart_gateway_container():
                        touch_cooldown(CONTAINER_RESTART_STATE)
                        write_fail_count(0)
                        action_taken = "restarted_gateway_container"
                        result = asyncio.run(probe_insync())
                    else:
                        action_taken = "container_restart_failed"
                elif state == "healthy":
                    logger.error("Gateway is logged in but probe fails; not restarting container")
                    action_taken += "+gateway_healthy_probe_fails"
                else:
                    logger.warning("Gateway login state unknown; not restarting container")
                    action_taken += "+gateway_state_unknown"

    if result.ok:
        logger.info("Probe OK: stage=%s duration_ms=%.1f server_version=%s managed_accounts=%s", result.stage, result.duration_ms, result.server_version, result.managed_accounts)
        # Gateway path is fine — make sure the backend's own sessions are too.
        backend_actions = ensure_backend_sessions()
        if backend_actions:
            action_taken = f"{action_taken}+{backend_actions}" if action_taken != "none" else backend_actions
    else:
        logger.error("Probe still failing: stage=%s error=%s", result.stage, result.error)

    log_to_postgres(result, action_taken)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
