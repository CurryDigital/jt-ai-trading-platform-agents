"""
Hub Service
===========
The running Hub service that routes events between agents.

This is the persistent coordinator that:
1. Listens for events (from agents or external sources)
2. Persists events to the database
3. Dispatches notifications to target agents via sessions_send

Usage:
    # Start the hub service
    python -m hub.service
    
    # Or from code:
    from hub.service import HubService
    service = HubService()
    service.start()
"""

import os
import sys
import json
import time
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from hub.router import HubRouter, Event, get_hub

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("hub_service")


class HubService:
    """
    The Hub Service - persistent event router.
    
    This service runs continuously (or as needed) to route events.
    In practice, it can be:
    - A long-running process that polls for new events
    - Triggered by database triggers
    - Invoked directly when agents emit events
    """
    
    def __init__(self, db_url: Optional[str] = None):
        """
        Initialize the Hub Service.
        
        Args:
            db_url: PostgreSQL connection URL
        """
        self.hub = HubRouter(db_url)
        self.running = False
        self.poll_interval = 1.0  # seconds
        
        logger.info("Hub Service initialized")
    
    def emit_and_route(
        self,
        event_type: str,
        strategy_id: Optional[str] = None,
        payload: Dict[str, Any] = None,
        source_agent: str = "unknown"
    ) -> List[Dict]:
        """
        Emit an event and route it to target agents.
        
        This is the main entry point for event emission.
        Returns the list of dispatch notifications that should be sent.
        
        Args:
            event_type: Type of event
            strategy_id: Associated strategy ID
            payload: Event payload
            source_agent: Agent that emitted the event
            
        Returns:
            List of dispatch info dicts with session_key and notification
        """
        payload = payload or {}
        
        # Step 1: Persist event
        event_id = self.hub._persist_event(event_type, strategy_id, payload, source_agent)
        logger.info(f"Event persisted: {event_type} (id={event_id}, strategy={strategy_id})")
        
        # Step 2: Get routing targets
        target_agents = self.hub._get_routing_targets(event_type)
        logger.info(f"Routing {event_type} to: {target_agents}")
        
        # Step 3: Build dispatch list
        dispatches = []
        for agent_name in target_agents:
            dispatch = self.hub._dispatch_to_agent(agent_name, event_id, event_type, strategy_id)
            if dispatch:
                dispatches.append(dispatch)
        
        return dispatches
    
    def process_dispatches(self, dispatches: List[Dict]):
        """
        No-op: sessions_send is now called directly inside
        HubRouter._dispatch_to_agent (via openclaw.tools.sessions_send).
        This method is kept for callers that iterate emit_and_route()'s return value.
        """
        for dispatch in dispatches:
            logger.info(
                f"[DISPATCHED] {dispatch.get('agent_name')} "
                f"@ {dispatch.get('session_key')}: {dispatch.get('notification')}"
            )
    
    def poll_and_route(self):
        """
        Poll for unprocessed events and route them.
        
        This is useful for batch processing or recovery scenarios.
        """
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Find events that haven't been fully routed
                # (This is a simplified check - in production, track routing status)
                cur.execute("""
                    SELECT id, event_type, strategy_id, payload_json, source_agent
                    FROM openclaw_researcher.events
                    WHERE created_at > NOW() - INTERVAL '1 hour'
                    ORDER BY created_at ASC
                    LIMIT 100
                """)
                
                for row in cur.fetchall():
                    event_id = str(row["id"])
                    event_type = row["event_type"]
                    strategy_id = row["strategy_id"]
                    payload = row["payload_json"]
                    if isinstance(payload, str):
                        payload = json.loads(payload)
                    source_agent = row["source_agent"]
                    
                    # Route this event
                    dispatches = self.emit_and_route(
                        event_type=event_type,
                        strategy_id=strategy_id,
                        payload=payload,
                        source_agent=source_agent
                    )
                    
                    if dispatches:
                        self.process_dispatches(dispatches)
                        
        finally:
            conn.close()
    
    def start(self, blocking: bool = True):
        """
        Start the Hub Service.
        
        Args:
            blocking: If True, run forever. If False, return immediately.
        """
        self.running = True
        logger.info("Hub Service started")
        
        # Emit system startup event
        dispatches = self.emit_and_route(
            event_type="system.startup",
            payload={"message": "Hub Service started"},
            source_agent="hub"
        )
        self.process_dispatches(dispatches)
        
        if blocking:
            try:
                while self.running:
                    self.poll_and_route()
                    time.sleep(self.poll_interval)
            except KeyboardInterrupt:
                logger.info("Hub Service stopped by user")
            finally:
                self.running = False
    
    def stop(self):
        """Stop the Hub Service."""
        self.running = False
        logger.info("Hub Service stopping...")


def emit_event(
    event_type: str,
    strategy_id: Optional[str] = None,
    payload: Dict[str, Any] = None,
    source_agent: str = "unknown",
    db_url: Optional[str] = None
) -> str:
    """
    Convenience function to emit an event from any agent.
    Uses the singleton HubRouter to avoid creating a new connection per call.

    Args:
        event_type: Type of event
        strategy_id: Associated strategy ID
        payload: Event payload
        source_agent: Agent that emitted the event
        db_url: Database URL (ignored — uses singleton)

    Returns:
        The event ID
    """
    hub = get_hub()
    return hub.emit_event(
        event_type=event_type,
        strategy_id=strategy_id,
        payload=payload,
        source_agent=source_agent,
    )


def main():
    """Main entry point for running the Hub Service."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Hub Event Router Service")
    parser.add_argument(
        "--db-url",
        help="PostgreSQL connection URL",
        default=os.environ.get("HUB_DATABASE_URL")
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds"
    )
    parser.add_argument(
        "--emit",
        help="Emit a single event and exit (format: type:strategy_id:payload_json)"
    )
    
    args = parser.parse_args()
    
    service = HubService(db_url=args.db_url)
    service.poll_interval = args.poll_interval
    
    if args.emit:
        # Single event emission mode
        parts = args.emit.split(":", 2)
        event_type = parts[0]
        strategy_id = parts[1] if len(parts) > 1 else None
        payload = json.loads(parts[2]) if len(parts) > 2 else {}
        
        event_id = emit_event(
            event_type=event_type,
            strategy_id=strategy_id,
            payload=payload,
            source_agent="cli"
        )
        print(f"Event emitted: {event_id}")
    else:
        # Run service
        service.start()


if __name__ == "__main__":
    main()
