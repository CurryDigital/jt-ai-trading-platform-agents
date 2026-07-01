#!/usr/bin/env python3
"""
Shared database connection module for Hermes ETL Manager.

Connection contract:
- Uses credentials from ~/.hermes/profiles/qr_etl/env/etl.env
- Module-level connection pool (max 2 connections per process) + auto-cleanup on exit
- 2026-06-15: pool guard prevents max_connections exhaustion
- 2026-06-22: psycopg2 / dotenv imports moved INSIDE _get_pool() so this module
  can be imported when those packages are missing. The error surfaces at first
  connection attempt with an actionable message naming the Hermes venv to fix,
  instead of crashing every bronze/silver/gold script at import time with an
  opaque ModuleNotFoundError that hides which env is broken.
"""

import os
import atexit
import sys

# Module-level connection pool (singleton)
_threaded_pool = None


def _missing_deps_help() -> str:
    """Operator-facing message naming the exact venv to fix."""
    venv = sys.prefix if sys.prefix else "<unknown>"
    return (
        "\n"
        "ETL DB driver missing in this Python environment.\n"
        f"  sys.prefix = {venv}\n"
        f"  sys.executable = {sys.executable}\n"
        "Run the Hermes bootstrap script on the box:\n"
        "    bash bootstrap_hermes_venv.sh\n"
        "Or install manually into the active venv:\n"
        "    pip install psycopg2-binary python-dotenv\n"
    )


def _load_env_and_imports():
    """Defer heavy imports until we actually need a connection."""
    try:
        import psycopg2
        from psycopg2 import pool
        from dotenv import load_dotenv
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(f"{e}.{_missing_deps_help()}") from e

    env_path = os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env')
    load_dotenv(env_path, override=True)
    return psycopg2, pool


def _get_pool():
    global _threaded_pool
    if _threaded_pool is None:
        psycopg2, pool = _load_env_and_imports()

        required = ['DB_HOST', 'DB_USER', 'DB_NAME', 'DB_PASSWORD']
        missing = [k for k in required if not os.environ.get(k)]
        if missing:
            raise RuntimeError(
                f"DB env missing: {missing}. "
                f"Source ~/.hermes/profiles/qr_etl/env/etl.env before running."
            )

        _threaded_pool = pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=2,  # max 2 connections per Python process
            host=os.environ['DB_HOST'],
            port=int(os.environ.get('DB_PORT', 5432)),
            user=os.environ['DB_USER'],
            dbname=os.environ['DB_NAME'],
            password=os.environ['DB_PASSWORD'],
            sslmode='require',
        )
        atexit.register(_close_pool)

    return _threaded_pool


def _close_pool():
    global _threaded_pool
    if _threaded_pool is not None:
        _threaded_pool.closeall()
        _threaded_pool = None


def get_connection():
    """
    Get a connection from the threaded pool.
    CALLER MUST call conn.close() to return it to the pool.

    On missing deps: raises ModuleNotFoundError with a message that names the
    Hermes venv and the bootstrap fix — see _missing_deps_help().
    """
    psycopg2, pool = _load_env_and_imports()
    try:
        return _get_pool().getconn()
    except pool.PoolError:
        # Pool exhausted — fall back to direct connection (last resort)
        return psycopg2.connect(
            host=os.environ['DB_HOST'],
            port=int(os.environ.get('DB_PORT', 5432)),
            user=os.environ['DB_USER'],
            dbname=os.environ['DB_NAME'],
            password=os.environ['DB_PASSWORD'],
            sslmode='require',
        )


def check_deps() -> bool:
    """
    Smoke test the import contract WITHOUT opening a DB connection.
    Returns True if psycopg2 + dotenv are importable, False otherwise.
    Daily refresh scripts call this before running anything else.
    """
    try:
        _load_env_and_imports()
        return True
    except ModuleNotFoundError as e:
        print(str(e), file=sys.stderr)
        return False
