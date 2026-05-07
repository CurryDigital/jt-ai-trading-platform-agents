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
    Connect to PostgreSQL using EC2 IAM instance profile.
    No credentials in code — role is attached to the EC2 instance.

    Reads from .env using DB_* variable names:
        DB_HOST     — RDS endpoint
        DB_PORT     — default 5432
        DB_USER     — DB username
        DB_NAME     — database name
        DB_REGION   — AWS region, default ap-southeast-1
    """
    load_dotenv()

    host   = os.environ.get('DB_HOST') or os.environ.get('RDS_HOST')
    port   = int(os.environ.get('DB_PORT') or os.environ.get('RDS_PORT', 5432))
    user   = os.environ.get('DB_USER') or os.environ.get('RDS_USER')
    dbname = os.environ.get('DB_NAME') or os.environ.get('RDS_DBNAME')
    region = os.environ.get('DB_REGION') or os.environ.get('AWS_REGION', 'ap-southeast-1')

    if not all([host, user, dbname]):
        missing = [k for k, v in {
            'DB_HOST': host, 'DB_USER': user, 'DB_NAME': dbname
        }.items() if not v]
        raise EnvironmentError(
            f"Missing required DB environment variables: {missing}. "
            f"Check ~/.openclaw/.env"
        )

    # boto3 automatically uses EC2 instance profile — no credentials needed
    client = boto3.client('rds', region_name=region)
    token  = client.generate_db_auth_token(
        DBHostname=host,
        Port=port,
        DBUsername=user,
        Region=region
    )

    return psycopg2.connect(
        host=host,
        port=port,
        user=user,
        password=token,   # IAM token used as password
        dbname=dbname,
        sslmode='require'
    )


def get_schema():
    """Returns the schema prefix for all queries."""
    return os.environ.get('DB_SCHEMA', 'openclaw_researcher')


def schema(table):
    """
    Returns fully qualified table name.
    Usage: schema('events') → 'openclaw_researcher.events'
    """
    return f"{get_schema()}.{table}"
