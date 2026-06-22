#!/usr/bin/env python3
"""
Shared database connection module for Hermes ETL Manager.
Uses credentials from ~/.hermes/profiles/etl-manager/env/etl.env

2026-06-15: Added connection pool guard to prevent max_connections exhaustion.
            get_connection() now uses a module-level connection pool with
            max 2 connections per process + auto-cleanup on script exit.
"""

import os
import atexit
import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

# Module-level connection pool (singleton)
_threaded_pool = None

def _get_pool():
    global _threaded_pool
    if _threaded_pool is None:
        env_path = os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env')
        load_dotenv(env_path, override=True)
        
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
        
        # Register cleanup on process exit
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
    
    If pool is exhausted, falls back to a direct connection.
    """
    try:
        return _get_pool().getconn()
    except pool.PoolError:
        # Pool exhausted — fall back to direct connection (last resort)
        env_path = os.path.expanduser('~/.hermes/profiles/qr_etl/env/etl.env')
        load_dotenv(env_path, override=True)
        return psycopg2.connect(
            host=os.environ['DB_HOST'],
            port=int(os.environ.get('DB_PORT', 5432)),
            user=os.environ['DB_USER'],
            dbname=os.environ['DB_NAME'],
            password=os.environ['DB_PASSWORD'],
            sslmode='require',
        )
