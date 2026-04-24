#!/usr/bin/env python3
"""
Shared database connection module for OpenClaw Quant agents.
Uses EC2 IAM instance profile for RDS authentication.
"""

# ─────────────────────────────────────────────────
# REAL COLUMN NAMES — locked, do not deviate
# ─────────────────────────────────────────────────
# TABLE: events
#   id (uuid, PK)
#   event_type (not "type")
#   strategy_id (DIRECT COLUMN, nullable - NOT in payload_json!)
#   payload_json (jsonb, not "payload") contains:
#     -> experiment_id (NOT a direct column)
#     -> dataset_id
#     -> param_set
#     -> metrics
#   source_agent (agent that emitted this event)
#   created_at (timestamp with time zone)
#   domain (text, nullable)
#
# TABLE: event_processing
#   event_id (uuid, FK to events.id)
#   agent_name (not "agent_id")
#   processed_at (timestamp with time zone, nullable)
#
# TABLE: strategy_workflow
#   strategy_id (text, PK)
#   name (text, NOT NULL)
#   status (text, NOT NULL)
#   experiment_id (text)
#   dataset_id (text)
#   metrics (jsonb)
#   risk_score (real)
#   risk_flags (text)
#   risk_approved (boolean)
#   risk_notes (text)
#   risk_evaluated_at (timestamp)
#   created_at (timestamp with time zone)
#   updated_at (timestamp with time zone)
#
# TABLE: workflow_events
#   id (integer, PK)
#   strategy_id (text, FK to strategy_workflow, nullable)
#   event_type (text)
#   from_status (not "status")
#   to_status (not "status")
#   agent (not "agent_id")
#   data (jsonb, not "metadata")
#   created_at (timestamp with time zone)
#
# TABLE: routing_rules
#   target_agent (singular text, not JSON array)
#   no priority column
#   PK: event_type only
#
# STATUS FLOW:
#   workflow.stuck: in_progress → stuck
#   monitor_requeue: in_progress → requeued
#   workflow_failed: stuck → failed
# ─────────────────────────────────────────────────

import os
import boto3
import psycopg2
from dotenv import load_dotenv

def get_connection():
    """
    Connect to PostgreSQL using credentials from ~/.openclaw/.env
    Supports both password auth and IAM token auth based on DB_AUTH_METHOD.
    """
    load_dotenv(os.path.expanduser('~/.openclaw/.env'))
    
    host = os.environ['DB_HOST']
    port = int(os.environ.get('DB_PORT', 5432))
    user = os.environ['DB_USER']
    dbname = os.environ['DB_NAME']
    password = os.environ['DB_PASSWORD']
    ssl_mode = os.environ.get('DB_SSL', 'true')
    ssl_reject = os.environ.get('DB_SSL_REJECT_UNAUTHORIZED', 'false')
    auth_method = os.environ.get('DB_AUTH_METHOD', 'password')
    region = os.environ.get('DB_REGION', 'ap-southeast-1')
    
    if auth_method == 'iam':
        # boto3 automatically uses EC2 instance profile
        client = boto3.client('rds', region_name=region)
        password = client.generate_db_auth_token(
            DBHostname=host,
            Port=port,
            DBUsername=user,
            Region=region
        )
        sslmode = 'require'
    else:
        # Password auth from .env
        sslmode = 'require' if ssl_mode.lower() == 'true' else 'prefer'
    
    conn = psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        dbname=dbname,
        sslmode=sslmode
    )
    
    return conn
