"""
Hub Event Router Package
========================
Event-driven multi-agent architecture for quant research.

Quick Start:
    # Initialize database
    psql -f hub/schema.sql
    
    # Emit an event from an agent
    from hub import emit_event
    
    emit_event(
        event_type="backtest.completed",
        strategy_id="104",
        payload={"sharpe": 1.42, "drawdown": -0.08},
        source_agent="algo"
    )
    
    # The Hub automatically routes to the QA agent

Components:
    - router.HubRouter: Core routing logic
    - service.HubService: Running service with notification dispatch
    - sdk.Agent: Base class for agents
    - sdk.LineageRecorder: Strategy lineage tracking
"""

from hub.router import HubRouter, Event, get_hub, emit_event
from hub.sdk import Agent, LineageRecorder, parse_notification, handle_notification
from hub.service import HubService, emit_event as service_emit_event

__all__ = [
    # Router
    "HubRouter",
    "Event",
    "get_hub",
    "emit_event",
    
    # SDK
    "Agent",
    "LineageRecorder",
    "parse_notification",
    "handle_notification",
    
    # Service
    "HubService",
    "service_emit_event",
]

__version__ = "1.0.0"
