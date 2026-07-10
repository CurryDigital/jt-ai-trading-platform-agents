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


def cooldown_elapsed(state_path: Path) -> bool:
    if not state_path.exists():
        return True
    try:
        last = float(state_path.read_text().strip())
        return time.time() - last >= RESTART_COOLDOWN_SECONDS
    except Exception:
        return True


def touch_cooldown(state_path: Path):
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(str(time.time()))


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
    state_path = Path.home() / ".hermes" / "profiles" / "qr_etl" / "var" / "ibkr_watchdog_restart.state"
    action_taken = "none"

    result = asyncio.run(probe_insync())

    if not result.ok:
        logger.warning("Probe failed at stage %s: %s", result.stage, result.error)
        if cooldown_elapsed(state_path):
            if restart_tunnel():
                action_taken = "restarted_tunnel"
                touch_cooldown(state_path)
                result = asyncio.run(probe_insync())
            else:
                action_taken = "tunnel_restart_failed"
        else:
            logger.warning("Restart cooldown active; not restarting tunnel")
            action_taken = "cooldown_active"

    if result.ok:
        logger.info("Probe OK: stage=%s duration_ms=%.1f server_version=%s managed_accounts=%s", result.stage, result.duration_ms, result.server_version, result.managed_accounts)
    else:
        logger.error("Probe still failing: stage=%s error=%s", result.stage, result.error)

    log_to_postgres(result, action_taken)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
