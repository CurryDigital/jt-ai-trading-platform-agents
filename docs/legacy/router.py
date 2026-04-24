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
    
    Usage:
        hub = HubRouter()
        
        # Agent emits an event
        event_id = hub.emit_event(
            event_type="backtest.completed",
            strategy_id="104",
            payload={"sharpe": 1.42, "drawdown": -0.08},
            source_agent="algo_quant",
            domain="quant"
        )
        
        # Hub automatically routes to target agent(s)
    """
    
    # Domain-aware routing table
    # Key: (domain, event_type) -> List[target_agents]
    # Domain-aware routing table.
    # Agent names here MUST match the name passed to super().__init__() in each agent class.
    ROUTING_TABLE = {
        # Quant Research Domain — correct pipeline order: Risk gates before QA
        ("quant", "experiment.started"):  ["qr_data_validator"],
        ("quant", "dataset.ready"):       ["qr_algo"],
        ("quant", "backtest.completed"):  ["qr_risk"],   # Risk gates before QA
        ("quant", "risk.evaluated"):      ["qr_qa"],     
        ("quant", "qa.validated"):        ["qr_exp_manager", "qr_idea_intake"],  # Exp. Manager generates next params; Idea Intake notifies operator
        ("quant", "workflow.stuck"):      ["qr_monitor", "qr_idea_intake"],       # Monitor re-queues; Idea Intake alerts operator
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

    # Session keys for agentToAgent (sessions_send) notifications.
    # Keys MUST match ROUTING_TABLE agent names above.
    # Update values to the actual OpenClaw session keys for your workspace.
    AGENT_SESSIONS = {
        "qr_monitor":    "agent:qr_monitor:main",
        "qr_data_validator": "agent:qr_data_validator:main",
        "qr_algo":       "agent:qr_algo:main",
        "qr_risk":       "agent:qr_risk:main",
        "qr_qa":         "agent:qr_qa:main",
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
        """
        Initialize the Hub Router.
        
        Args:
            db_url: PostgreSQL connection URL. If None, uses HUB_DATABASE_URL env var.
        """
        self.db_url = db_url or os.environ.get(
            "HUB_DATABASE_URL",
            "postgresql://localhost:5432/hub_events"
        )
        self._init_db()
    
    def _get_conn(self):
        """Get a database connection using RDS IAM auth with search_path set."""
        import boto3
        from dotenv import load_dotenv
        load_dotenv()
        
        # Check if using IAM auth (RDS_HOST env var present)
        if os.environ.get('RDS_HOST') or os.environ.get('DB_HOST'):
            host = os.environ.get('RDS_HOST') or os.environ.get('DB_HOST')
            port = int(os.environ.get('RDS_PORT', 5432))
            user = os.environ.get('RDS_USER', 'openclaw_user')
            dbname = os.environ.get('RDS_DBNAME') or os.environ.get('DB_NAME', 'aitrading')
            region = os.environ.get('AWS_REGION', 'ap-southeast-1')
            
            # Generate IAM auth token
            client = boto3.client('rds', region_name=region)
            token = client.generate_db_auth_token(
                DBHostname=host,
                Port=port,
                DBUsername=user,
                Region=region
            )
            
            return psycopg2.connect(
                host=host,
                port=port,
                user=user,
                password=token,
                dbname=dbname,
                sslmode='require',
                options='-c search_path=openclaw_researcher,public'
            )
        else:
            # Fallback to standard connection URL
            return psycopg2.connect(self.db_url)
    
    def _init_db(self):
        """Initialize database connection and verify schema."""
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
        """
        Emit an event to the system.
        
        The Hub will:
        1. Persist the event to the database
        2. Look up routing rules
        3. Dispatch notifications to target agents
        
        Args:
            event_type: Type of event (e.g., "backtest.completed")
            strategy_id: Associated strategy ID (optional)
            payload: Event payload as dict
            source_agent: Name of the emitting agent
            domain: Domain - "quant" (research) or "platform" (engineering)
            
        Returns:
            The event ID (UUID string)
        """
        payload = payload or {}
        
        # Step 1: Persist event to database
        event_id = self._persist_event(event_type, strategy_id, payload, source_agent, domain)
        logger.info(f"Event emitted: {event_type} (id={event_id}, strategy={strategy_id}, domain={domain})")
        
        # Step 2: Look up routing rules
        target_agents = self._get_routing_targets(event_type, domain)
        
        # Step 3: Dispatch to each target agent
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
        """Persist event to database."""
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
        """Get target agents for an event type and domain."""
        # First check static routing table (domain-aware)
        key = (domain, event_type)
        if key in self.ROUTING_TABLE:
            return self.ROUTING_TABLE[key]
        
        # Fall back to database routing rules
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
        """
        Dispatch event notification to an agent via OpenClaw sessions_send.

        Message format: event:{domain}:{event_type}:{strategy_id}
        Example:        event:quant:backtest.completed:strat-uuid-123

        sessions_send is the OpenClaw agentToAgent API. It delivers the
        notification string to the target agent's active session, waking
        it up. The agent then pulls its pending events from the DB and
        processes them before exiting.
        """
        session_key = self.AGENT_SESSIONS.get(agent_name)
        if not session_key:
            logger.warning(f"No session key configured for agent: {agent_name}")
            return None

        # Build notification message
        if strategy_id:
            notification = f"event:{domain}:{event_type}:{strategy_id}"
        else:
            notification = f"event:{domain}:{event_type}"

        logger.info(f"Dispatching to {agent_name} @ {session_key}: {notification}")

        # ── Real sessions_send call ──────────────────────────────────────────
        # OpenClaw exposes sessions_send as a tool available to the Hub agent.
        # When the Hub agent receives a new event (via its own on_event loop or
        # a direct DB-trigger invocation), it calls this function which uses the
        # sessions_send tool to wake the target agent.
        #
        # The Hub agent's system prompt must include the sessions_send tool.
        # Usage: sessions_send(session_key=<key>, message=<notification>)
        #
        # We call it here through the OpenClaw tool interface. If the Hub is
        # running as a Python subprocess (not inside an agent session), fall
        # back to writing to the notification queue so the agent's poll loop
        # picks it up on its next cycle.
        try:
            # Import the OpenClaw tool bridge (available inside agent sessions)
            from openclaw.tools import sessions_send  # type: ignore
            sessions_send(session_key=session_key, message=notification)
            logger.info(f"sessions_send OK → {agent_name}")
        except ImportError:
            # Running outside an OpenClaw agent session (e.g. CLI, tests).
            # Write to the notification queue as a fallback; agents with a
            # poll loop (monitor_agent) will pick this up automatically.
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
        """
        Fallback used when sessions_send is unavailable (outside agent session).
        Writes to .notification_queue so poll-based agents / tests can consume it.
        """
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
        """Retrieve an event by ID."""
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
        """
        Derive which event_types an agent handles from the static ROUTING_TABLE.
        This avoids depending on the routing_rules DB table being populated.
        """
        event_types = []
        for (d, et), agents in self.ROUTING_TABLE.items():
            if agent_name in agents:
                if domain is None or d == domain:
                    event_types.append(et)
        return event_types

    def get_pending_events(self, agent_name: str, domain: Optional[str] = None) -> List[Event]:
        """
        Get all pending events for an agent, optionally filtered by domain.
        Uses the static ROUTING_TABLE to determine which event types this agent
        handles — does NOT depend on routing_rules DB table being populated.
        """
        # Derive event types from static routing table
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
        """Record that an agent has processed an event."""
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
        """Get event log, optionally filtered by strategy and/or domain."""
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
