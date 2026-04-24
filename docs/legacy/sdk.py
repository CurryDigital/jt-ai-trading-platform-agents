"""
Agent SDK
=========
Base classes and utilities for agents participating in the event-driven architecture.

Agents follow this pattern:
1. Receive event notification from Hub
2. Load event payload from database
3. Perform work
4. Emit new event(s) to Hub
5. Exit

Example:
    from hub.sdk import Agent, Event
    
    class AlgoAgent(Agent):
        def __init__(self):
            super().__init__("algo")
        
        def on_event(self, event: Event):
            if event.event_type == "dataset.ready":
                # Load data, run backtest
                result = self.run_backtest(event)
                
                # Emit completion event
                self.emit_event(
                    event_type="backtest.completed",
                    strategy_id=event.strategy_id,
                    payload=result
                )
    
    agent = AlgoAgent()
    agent.run()  # Processes pending events and exits
"""

import os
import json
import logging
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from datetime import datetime

from hub.router import HubRouter, Event, get_hub

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("agent")


class LineageRecorder:
    """
    Records strategy lineage for experiment reproducibility.
    Used by the Algo agent to track experiments.
    """
    
    def __init__(self, hub: HubRouter):
        self.hub = hub
    
    def record(
        self,
        strategy_id: str,
        dataset_version: str,
        backtest_engine_version: str,
        strategy_parameters: Dict[str, Any],
        result_metrics: Dict[str, Any],
        source_event_id: str
    ) -> str:
        """
        Record a strategy lineage entry.
        
        Args:
            strategy_id: Strategy identifier
            dataset_version: Dataset version (e.g., "equities_daily_v3")
            backtest_engine_version: Engine version (e.g., "engine_v2.1")
            strategy_parameters: Dict of parameters used
            result_metrics: Dict of results (sharpe, drawdown, etc.)
            source_event_id: The event that produced this result
            
        Returns:
            Lineage entry ID
        """
        import psycopg2
        
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO openclaw_researcher.strategy_lineage (
                        strategy_id, dataset_version, backtest_engine_version,
                        strategy_parameters, result_metrics, source_event_id
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    strategy_id,
                    dataset_version,
                    backtest_engine_version,
                    json.dumps(strategy_parameters),
                    json.dumps(result_metrics),
                    source_event_id
                ))
                lineage_id = cur.fetchone()[0]
                conn.commit()
                logger.info(f"Recorded lineage for strategy {strategy_id}: {lineage_id}")
                return str(lineage_id)
        finally:
            conn.close()
    
    def get_lineage(self, strategy_id: str) -> List[Dict]:
        """Get all lineage entries for a strategy."""
        import psycopg2
        from psycopg2.extras import RealDictCursor
        
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute("""
                    SELECT * FROM openclaw_researcher.strategy_lineage
                    WHERE strategy_id = %s
                    ORDER BY created_at DESC
                """, (strategy_id,))
                rows = cur.fetchall()
                return [
                    {
                        "id": str(row["id"]),
                        "strategy_id": row["strategy_id"],
                        "dataset_version": row["dataset_version"],
                        "backtest_engine_version": row["backtest_engine_version"],
                        "strategy_parameters": json.loads(row["strategy_parameters"]),
                        "result_metrics": json.loads(row["result_metrics"]),
                        "source_event_id": str(row["source_event_id"]),
                        "created_at": row["created_at"].isoformat() if row["created_at"] else None
                    }
                    for row in rows
                ]
        finally:
            conn.close()
    
    def compare_experiments(self, strategy_id: str, metric: str = "sharpe") -> List[Dict]:
        """
        Compare all experiments for a strategy on a specific metric.
        
        Returns a list sorted by the metric value (descending).
        """
        lineage = self.get_lineage(strategy_id)
        
        comparison = []
        for entry in lineage:
            metrics = entry.get("result_metrics", {})
            params = entry.get("strategy_parameters", {})
            comparison.append({
                "lineage_id": entry["id"],
                "dataset_version": entry["dataset_version"],
                "engine_version": entry["backtest_engine_version"],
                "parameters": params,
                "metric_value": metrics.get(metric),
                "all_metrics": metrics,
                "created_at": entry["created_at"]
            })
        
        # Sort by metric value (descending)
        comparison.sort(key=lambda x: x["metric_value"] or 0, reverse=True)
        return comparison


class RetryableError(Exception):
    """
    Raise this from on_event() when the agent wants to retry later.
    The SDK will NOT mark the event as processed, so it stays pending
    for the next run() cycle.

    Usage in agent:
        from hub.sdk import RetryableError

        def on_event(self, event):
            if not ready:
                raise RetryableError("Gold layer locked, will retry")
    """
    pass


class Agent(ABC):
    """
    Base class for all agents in the event-driven architecture.
    
    Agents are stateless workers that:
    1. Receive event notifications
    2. Load event data from DB
    3. Perform work
    4. Emit new events
    5. Exit
    
    Subclasses must implement on_event() to handle specific event types.

    Retry semantics:
      - If on_event() returns normally → event is marked processed.
      - If on_event() raises RetryableError → event stays pending for retry.
      - If on_event() raises any other Exception → event stays pending, error is logged.
    """
    
    def __init__(self, agent_name: str, domain: str = "quant", hub: Optional[HubRouter] = None):
        """
        Initialize the agent.
        
        Args:
            agent_name: Unique name for this agent (e.g., "algo_quant", "platform_dev")
            domain: Domain - "quant" (research) or "platform" (engineering)
            hub: HubRouter instance (creates default if None)
        """
        self.agent_name = agent_name
        self.domain = domain
        self.hub = hub or get_hub()
        self.lineage = LineageRecorder(self.hub)
        self._handlers: Dict[str, Callable] = {}
        
        logger.info(f"Agent '{agent_name}' initialized (domain: {domain})")
    
    def register_handler(self, event_type: str, handler: Callable):
        """Register a handler for a specific event type."""
        self._handlers[event_type] = handler
        logger.info(f"Registered handler for {event_type}")
    
    def emit_event(
        self,
        event_type: str,
        strategy_id: Optional[str] = None,
        payload: Dict[str, Any] = None
    ) -> str:
        """
        Emit an event to the Hub.
        
        The Hub will route this to the appropriate next agent(s).
        
        Args:
            event_type: Type of event
            strategy_id: Associated strategy ID
            payload: Event payload data
            
        Returns:
            Event ID
        """
        return self.hub.emit_event(
            event_type=event_type,
            strategy_id=strategy_id,
            payload=payload,
            source_agent=self.agent_name,
            domain=self.domain
        )
    
    def get_pending_events(self, filter_domain: Optional[str] = None) -> List[Event]:
        """Get all pending events for this agent, optionally filtered by domain."""
        domain = filter_domain or self.domain
        return self.hub.get_pending_events(self.agent_name, domain)
    
    def load_event(self, event_id: str) -> Optional[Event]:
        """Load a specific event by ID."""
        return self.hub.get_event(event_id)
    
    def mark_processed(self, event_id: str):
        """Mark an event as processed by this agent."""
        self.hub.record_processing(event_id, self.agent_name)
    
    @abstractmethod
    def on_event(self, event: Event):
        """
        Process an event. Subclasses must implement this.
        
        This method should:
        1. Perform the agent's work
        2. Emit new events as needed
        3. Not return any value
        """
        pass
    
    def run(self, single_event: Optional[str] = None):
        """
        Run the agent - process pending events.

        Retry semantics:
          - RetryableError → event stays pending (not marked processed)
          - Other Exception → event stays pending, error logged, continues to next
          - Success → event marked processed
        
        Args:
            single_event: If provided, process only this event ID (for targeted execution)
        """
        if single_event:
            # Process a specific event
            event = self.load_event(single_event)
            if not event:
                logger.error(f"Event not found: {single_event}")
                return
            
            logger.info(f"Processing event {event.id}: {event.event_type}")
            try:
                self.on_event(event)
                self.mark_processed(event.id)
                logger.info(f"Completed processing event {event.id}")
            except RetryableError as e:
                logger.warning(f"Retryable: event {event.id} will retry later: {e}")
                # Do NOT mark processed — event stays pending
            except Exception as e:
                logger.error(f"Error processing event {event.id}: {e}")
                raise
        else:
            # Process all pending events
            events = self.get_pending_events()
            
            if not events:
                logger.info(f"No pending events for {self.agent_name}")
                return
            
            logger.info(f"Found {len(events)} pending events")
            
            for event in events:
                logger.info(f"Processing event {event.id}: {event.event_type}")
                try:
                    # Check if handler registered
                    if event.event_type in self._handlers:
                        self._handlers[event.event_type](event)
                    else:
                        self.on_event(event)
                    
                    self.mark_processed(event.id)
                    logger.info(f"Completed processing event {event.id}")
                except RetryableError as e:
                    logger.warning(f"Retryable: event {event.id} will retry later: {e}")
                    # Do NOT mark processed — event stays pending
                except Exception as e:
                    logger.error(f"Error processing event {event.id}: {e}")
                    # Do NOT mark processed — event stays pending for retry
                    # Continue with next event - don't stop on error


def parse_notification(notification: str) -> Dict[str, Optional[str]]:
    """
    Parse an event notification from the Hub.
    
    Format: event:{domain}:{event_type}:{strategy_id}
    Example: event:quant:backtest.completed:104
    
    Returns:
        Dict with domain, event_type and strategy_id (may be None)
    """
    parts = notification.split(":")
    
    if len(parts) < 3 or parts[0] != "event":
        raise ValueError(f"Invalid notification format: {notification}")
    
    domain = parts[1]
    event_type = parts[2]
    strategy_id = parts[3] if len(parts) > 3 else None
    
    return {
        "domain": domain,
        "event_type": event_type,
        "strategy_id": strategy_id
    }


def handle_notification(agent: Agent, notification: str):
    """
    Handle an event notification received via sessions_send.
    
    This is the entry point for agents when they receive a notification.
    
    Args:
        agent: The agent instance
        notification: The notification string (e.g., "event:quant:backtest.completed:104")
    """
    parsed = parse_notification(notification)
    
    # Find the event in the database
    # If strategy_id is provided, look for recent events of that type in the domain
    if parsed["strategy_id"]:
        events = agent.hub.get_event_log(
            strategy_id=parsed["strategy_id"], 
            domain=parsed["domain"],
            limit=10
        )
        for event in events:
            if event.event_type == parsed["event_type"]:
                agent.run(single_event=event.id)
                return
        logger.error(f"Event not found: {parsed['event_type']} for strategy {parsed['strategy_id']} in domain {parsed['domain']}")
    else:
        # No strategy ID - get most recent event of this type in the domain
        events = agent.hub.get_event_log(domain=parsed["domain"], limit=50)
        for event in events:
            if event.event_type == parsed["event_type"]:
                agent.run(single_event=event.id)
                return
        logger.error(f"Event not found: {parsed['event_type']} in domain {parsed['domain']}")
        events = agent.hub.get_event_log(limit=50)
        for event in events:
            if event.event_type == parsed["event_type"]:
                agent.run(single_event=event.id)
                return
        logger.error(f"Event not found: {parsed['event_type']}")
