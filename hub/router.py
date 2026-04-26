"""
Hub Event Router
================
The central event router for the multi-agent architecture.

Responsibilities:
- Receive events from agents via emit_event()
- Persist events to PostgreSQL
- Route events to target agents based on routing rules
- Notify agents using sessions_send (agentToAgent)

The Hub does NOT implement workflow logic - only applies routing rules.
"""

import os
import json
import uuid
import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hub")


@dataclass
class Event:
    """Represents a system event."""
    id: Optional[str]
    event_type: str
    strategy_id: Optional[str]
    payload: Dict[str, Any]
    source_agent: str
    domain: str = "quant"  # 'quant' or 'platform'
    created_at: Optional[datetime] = None

    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "event_type": self.event_type,
            "strategy_id": self.strategy_id,
            "payload": self.payload,
            "source_agent": self.source_agent,
            "domain": self.domain,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }


class HubRouter:
    """
    The Hub Event Router - central coordination point for all agents.
    """

    # Domain-aware routing table.
    ROUTING_TABLE = {
        # Quant Research Domain — correct pipeline order: Risk gates before QA
        ("quant", "experiment.started"):  ["qr_data_validator"],
        ("quant", "dataset.ready"):       ["qr_algo"],
        ("quant", "backtest.completed"):  ["qr_risk"],   # Risk gates before QA
        # qr_debate runs as a parallel observer of risk.evaluated (telemetry only).
        # qr_qa does not depend on its output, so debate failures cannot stall QA.
        ("quant", "risk.evaluated"):      ["qr_qa", "qr_debate"],
        ("quant", "qa.validated"):        ["qr_exp_manager", "qr_idea_intake"],
        ("quant", "workflow.stuck"):      ["qr_monitor", "qr_idea_intake"],       
        ("quant", "system.startup"):      ["qr_monitor"],
        ("quant", "etl.completed"):       ["qr_monitor"],
        ("quant", "etl.partial"):         ["qr_monitor", "qr_idea_intake"],
        ("quant", "etl.failed"):          ["qr_monitor", "qr_idea_intake"],
        ("quant", "etl.operator_alert"): ["qr_idea_intake"],
        ("quant", "etl.refresh_requested"): ["qr_etl_manager"],

        # Platform Engineering Domain
        ("platform", "feature.requested"):    ["platform_dev"],
        ("platform", "code.generated"):       ["qa_code"],
        ("platform", "code.tested"):          ["platform_ops"],
        ("platform", "deployment.completed"): ["platform_monitor"],
        ("platform", "system.startup"):       ["platform_monitor"],
    }

    AGENT_SESSIONS = {
        "qr_monitor":    "agent:qr_monitor:main",
        "qr_data_validator": "agent:qr_data_validator:main",
        "qr_algo":       "agent:qr_algo:main",
        "qr_risk":       "agent:qr_risk:main",
        "qr_qa":         "agent:qr_qa:main",
        "qr_debate":     "agent:qr_debate:main",
        "qr_exp_manager":    "agent:qr_exp_manager:main",
        "qr_idea_intake":    "agent:qr_idea_intake:main",
        "qr_hub":            "agent:qr_hub:main",
        "qr_etl_manager":    "agent:qr_etl_manager:main",
        # Platform domain agents
        "platform_dev":     "agent:platform_dev:main",
        "qa_code":          "agent:qa_code:main",
        "platform_ops":     "agent:platform_ops:main",
        "platform_monitor": "agent:platform_monitor:main",
    }

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ.get(
            "HUB_DATABASE_URL",
            "postgresql://localhost:5432/hub_events"
        )
        self._init_db()

    def _get_conn(self):
        """Get a database connection using standard password auth with search_path set."""
        from dotenv import load_dotenv
        load_dotenv()

        host = os.environ.get('RDS_HOST') or os.environ.get('DB_HOST', 'openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com')
        port = int(os.environ.get('RDS_PORT', os.environ.get('DB_PORT', 5432)))
        user = os.environ.get('RDS_USER', os.environ.get('DB_USER', 'openclaw_user'))
        dbname = os.environ.get('RDS_DBNAME') or os.environ.get('DB_NAME', 'aitrading')

        # Read static password directly from .env to bypass IAM
        db_pass = ""
        try:
            with open('/home/ubuntu/.openclaw/.env', 'r') as f:
                for line in f:
                    if line.startswith('DB_PASSWORD='):
                        db_pass = line.strip().split('=', 1)[1].strip('"\'')
                        break
        except Exception:
            db_pass = os.environ.get('DB_PASSWORD', '')

        return psycopg2.connect(
            host=host,
            port=port,
            user=user,
            password=db_pass,
            dbname=dbname,
            sslmode='require',
            options='-c search_path=openclaw_researcher,public'
        )

    def _init_db(self):
        try:
            conn = self._get_conn()
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM openclaw_researcher.events LIMIT 1")
            conn.close()
            logger.info("Hub Router connected to database")
        except Exception as e:
            logger.error(f"Database not initialized. Run schema.sql first. Error: {e}")
            raise

    def emit_event(
        self,
        event_type: str,
        strategy_id: Optional[str] = None,
        payload: Dict[str, Any] = None,
        source_agent: str = "unknown",
        domain: str = "quant"
    ) -> str:
        payload = payload or {}
        event_id = self._persist_event(event_type, strategy_id, payload, source_agent, domain)
        logger.info(f"Event emitted: {event_type} (id={event_id}, strategy={strategy_id}, domain={domain})")
        target_agents = self._get_routing_targets(event_type, domain)
        for agent in target_agents:
            self._dispatch_to_agent(agent, event_id, event_type, strategy_id, domain)
        return event_id

    def _persist_event(
        self,
        event_type: str,
        strategy_id: Optional[str],
        payload: Dict[str, Any],
        source_agent: str,
        domain: str = "quant"
    ) -> str:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO openclaw_researcher.events (event_type, strategy_id, payload_json, source_agent, domain)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                """, (event_type, strategy_id, json.dumps(payload), source_agent, domain))
                event_id = cur.fetchone()[0]
                conn.commit()
                return str(event_id)
        finally:
            conn.close()

    def _get_routing_targets(self, event_type: str, domain: str = "quant") -> List[str]:
        key = (domain, event_type)
        if key in self.ROUTING_TABLE:
            return self.ROUTING_TABLE[key]

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT target_agent FROM openclaw_researcher.routing_rules
                    WHERE event_type = %s AND domain = %s AND enabled = TRUE
                """, (event_type, domain))
                rows = cur.fetchall()
                return [row[0] for row in rows]
        finally:
            conn.close()

    def _dispatch_to_agent(
        self,
        agent_name: str,
        event_id: str,
        event_type: str,
        strategy_id: Optional[str],
        domain: str = "quant"
    ):
        session_key = self.AGENT_SESSIONS.get(agent_name)
        if not session_key:
            logger.warning(f"No session key configured for agent: {agent_name}")
            return None

        if strategy_id:
            notification = f"event:{domain}:{event_type}:{strategy_id}"
        else:
            notification = f"event:{domain}:{event_type}"

        logger.info(f"Dispatching to {agent_name} @ {session_key}: {notification}")

        try:
            from openclaw.tools import sessions_send  # type: ignore
            sessions_send(session_key=session_key, message=notification)
            logger.info(f"sessions_send OK → {agent_name}")
        except ImportError:
            self._queue_notification_fallback(
                agent_name, session_key, notification, event_id, domain
            )

        return {
            "session_key": session_key,
            "agent_name": agent_name,
            "notification": notification,
            "event_id": event_id,
            "domain": domain,
        }

    def _queue_notification_fallback(
        self,
        agent_name: str,
        session_key: str,
        notification: str,
        event_id: str,
        domain: str,
    ):
        import time
        queue_file = os.path.join(os.path.dirname(__file__), ".notification_queue")
        with open(queue_file, "a") as f:
            f.write(json.dumps({
                "timestamp": time.time(),
                "agent_name": agent_name,
                "session_key": session_key,
                "notification": notification,
                "event_id": event_id,
                "domain": domain,
            }) + "\n")
        logger.info(f"Queued notification for {agent_name} (sessions_send unavailable)")

    def get_event(self, event_id: str) -> Optional[Event]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT id, event_type, strategy_id, payload_json, source_agent, domain, created_at
                    FROM openclaw_researcher.events WHERE id = %s
                """, (event_id,))
                row = cur.fetchone()
                if row:
                    return Event(
                        id=str(row["id"]),
                        event_type=row["event_type"],
                        strategy_id=row["strategy_id"],
                        payload=row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"]),
                        source_agent=row["source_agent"],
                        domain=row.get("domain", "quant"),
                        created_at=row["created_at"]
                    )
                return None
        finally:
            conn.close()

    def _get_event_types_for_agent(self, agent_name: str, domain: Optional[str] = None) -> List[str]:
        event_types = []
        for (d, et), agents in self.ROUTING_TABLE.items():
            if agent_name in agents:
                if domain is None or d == domain:
                    event_types.append(et)
        return event_types

    def get_pending_events(self, agent_name: str, domain: Optional[str] = None) -> List[Event]:
        event_types = self._get_event_types_for_agent(agent_name, domain)
        if not event_types:
            logger.info(f"No routing entries for agent {agent_name} (domain={domain})")
            return []

        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if domain:
                    cur.execute("""
                        SELECT e.id, e.event_type, e.strategy_id, e.domain, e.payload_json,
                               e.source_agent, e.created_at
                        FROM openclaw_researcher.events e
                        LEFT JOIN openclaw_researcher.event_processing ep
                            ON e.id = ep.event_id AND ep.agent_name = %s
                        WHERE e.event_type = ANY(%s)
                          AND e.domain = %s
                          AND ep.event_id IS NULL
                        ORDER BY e.created_at ASC
                    """, (agent_name, event_types, domain))
                else:
                    cur.execute("""
                        SELECT e.id, e.event_type, e.strategy_id, e.domain, e.payload_json,
                               e.source_agent, e.created_at
                        FROM openclaw_researcher.events e
                        LEFT JOIN openclaw_researcher.event_processing ep
                            ON e.id = ep.event_id AND ep.agent_name = %s
                        WHERE e.event_type = ANY(%s)
                          AND ep.event_id IS NULL
                        ORDER BY e.created_at ASC
                    """, (agent_name, event_types))

                events = []
                for row in cur.fetchall():
                    events.append(Event(
                        id=str(row["id"]),
                        event_type=row["event_type"],
                        strategy_id=row["strategy_id"],
                        payload=row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"]),
                        source_agent=row["source_agent"],
                        domain=row.get("domain", "quant"),
                        created_at=row["created_at"]
                    ))
                return events
        finally:
            conn.close()

    def record_processing(self, event_id: str, agent_name: str):
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO openclaw_researcher.event_processing (event_id, agent_name)
                    VALUES (%s, %s)
                    ON CONFLICT (event_id, agent_name) DO NOTHING
                """, (event_id, agent_name))
                conn.commit()
                logger.info(f"Recorded processing: {agent_name} processed event {event_id}")
        finally:
            conn.close()

    def get_event_log(self, strategy_id: Optional[str] = None, domain: Optional[str] = None, limit: int = 100) -> List[Event]:
        conn = self._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                if strategy_id and domain:
                    cur.execute("""
                        SELECT id, event_type, strategy_id, domain, payload_json,
                               source_agent, created_at
                        FROM openclaw_researcher.events
                        WHERE strategy_id = %s AND domain = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (strategy_id, domain, limit))
                elif strategy_id:
                    cur.execute("""
                        SELECT id, event_type, strategy_id, domain, payload_json,
                               source_agent, created_at
                        FROM openclaw_researcher.events
                        WHERE strategy_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (strategy_id, limit))
                elif domain:
                    cur.execute("""
                        SELECT id, event_type, strategy_id, domain, payload_json,
                               source_agent, created_at
                        FROM openclaw_researcher.events
                        WHERE domain = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (domain, limit))
                else:
                    cur.execute("""
                        SELECT id, event_type, strategy_id, domain, payload_json,
                               source_agent, created_at
                        FROM openclaw_researcher.events
                        ORDER BY created_at DESC
                        LIMIT %s
                    """, (limit,))

                events = []
                for row in cur.fetchall():
                    events.append(Event(
                        id=str(row["id"]),
                        event_type=row["event_type"],
                        strategy_id=row["strategy_id"],
                        payload=row["payload_json"] if isinstance(row["payload_json"], dict) else json.loads(row["payload_json"]),
                        source_agent=row["source_agent"],
                        domain=row.get("domain", "quant"),
                        created_at=row["created_at"]
                    ))
                return events
        finally:
            conn.close()


# Singleton instance for convenience
_hub_instance = None

def get_hub() -> HubRouter:
    """Get or create the singleton Hub Router instance."""
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = HubRouter()
    return _hub_instance


def emit_event(
    event_type: str,
    strategy_id: Optional[str] = None,
    payload: Dict[str, Any] = None,
    source_agent: str = "unknown",
    domain: str = "quant"
) -> str:
    """Convenience function to emit an event via the singleton hub."""
    return get_hub().emit_event(event_type, strategy_id, payload, source_agent, domain)
