#!/usr/bin/env python3
"""
Exp. Manager Agent (Hub-based) - OpenClaw Quant Pipeline
Pipeline subagent: Generates experiment variants and manages evolution.

Uses hub.sdk.Agent base class for event-driven architecture.
"""

import os
import json
import sys
import uuid
import copy
from datetime import datetime, timezone
from typing import Optional
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.sdk import Agent, Event, RetryableError

from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_EXP_MANAGER as AGENT_ID,
    FLOOD_CONTROL_LIMIT, MAX_VARIANTS_PER_CYCLE,
    EXP_PHASE1_THRESHOLD, EXP_PHASE1_VARIANTS_PASS, EXP_PHASE1_VARIANTS_FAIL,
    EXP_PHASE2_VARIANTS, EXP_DUPLICATE_LOOKBACK_DAYS,
    EXP_PRUNE_PASS_RATE, EXP_EXPAND_PASS_RATE, EXP_PRUNE_MIN_EXPERIMENTS,
    EXP_NIGHTLY_TOP_SHARPE, EXP_NIGHTLY_LOOKBACK_DAYS, EXP_NIGHTLY_FALLBACK_COUNT,
    PARAM_LOOKBACK_MIN, PARAM_LOOKBACK_MAX, PARAM_ENTRY_MIN, PARAM_ENTRY_MAX,
    PARAM_EXIT_MIN, PARAM_EXIT_MAX,
)


class ExpManagerAgent(Agent):
    """
    Experiment Manager agent.
    Consumes: qa.validated
    Emits: experiment.started (for each variant)
    """
    
    def __init__(self):
        super().__init__('qr_exp_manager', domain='quant')
    
    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == 'qa.validated':
            self._generate_experiments(event)
        else:
            self._log(f"Received unexpected event: {event.event_type}")
    
    def _generate_experiments(self, event: Event):
        """Generate experiment variants from a QA result."""
        event_id = event.id
        payload = event.payload or {}
        
        # Get strategy_id from event if not in payload
        strategy_id = payload.get('strategy_id') or event.strategy_id
        qa_passed = payload.get('passed', False)
        
        # Get experiment_id from strategy_workflow if not in payload
        experiment_id = payload.get('experiment_id')
        if not experiment_id and strategy_id:
            experiment_id = self._get_experiment_id_from_workflow(strategy_id)
        
        self._log(f"Processing QA result for experiment {experiment_id}: passed={qa_passed}")
        
        # Check flood control first
        if not self._check_flood_control():
            self._log("Flood control active. Skipping variant generation.")
            # Raise RetryableError so event stays pending for retry later
            raise RetryableError("Flood control active")
        
        try:
            # Recover parent param_set for variant generation
            parent_param_set, parent_generation = self._get_parent_param_set(experiment_id)
            
            if parent_param_set is None:
                self._log(f"WARNING: Could not recover param_set for {experiment_id}. Skipping variant generation.")
                return  # Mark as done - nothing to do
            
            # Get experiment count for phase determination
            exp_count = self._get_experiment_count()
            self._log(f"Current experiment count: {exp_count} (Phase {'2' if exp_count >= 50 else '1'})")
            
            # Generate variants from this result
            variants = self._generate_variants(
                parent_param_set,
                experiment_id=experiment_id,
                parent_generation=parent_generation
            )
            
            self._log(f"Generated {len(variants)} variants for experiment {experiment_id}")
            
            # Emit experiment.started for each variant
            emitted_count = 0
            for i, variant in enumerate(variants):
                new_experiment_id = str(uuid.uuid4())
                new_strategy_id = str(uuid.uuid4())
                
                # Create strategy_workflow entry first
                self._create_strategy_workflow(
                    strategy_id=new_strategy_id,
                    experiment_id=new_experiment_id,
                    param_set=variant['param_set'],
                    parent_experiment_id=experiment_id
                )
                
                # Emit event with proper strategy_id
                self.emit_event(
                    event_type='experiment.started',
                    strategy_id=new_strategy_id,
                    payload={
                        'experiment_id': new_experiment_id,
                        'strategy_id': new_strategy_id,
                        'param_set': variant['param_set'],
                        'generation': variant['generation'],
                        'parent_experiment_id': experiment_id
                    }
                )
                emitted_count += 1
            
            self._log_workflow_event('variants_generated', strategy_id,
                                    'pending', 'completed',
                                    {
                                        'parent_experiment_id': experiment_id,
                                        'variants_count': emitted_count,
                                        'parent_generation': parent_generation,
                                        'qa_passed': qa_passed
                                    })
            
            self._log(f"Completed processing experiment {experiment_id}")
            
        except Exception as e:
            self._log(f"ERROR processing experiment {experiment_id}: {str(e)}")
            self._log_workflow_event('variant_generation_failed', strategy_id,
                                    'in_progress', 'failed',
                                    {'event_id': str(event_id), 'error': str(e)})
            raise
    
    def _check_flood_control(self):
        """
        Check if there are too many experiments in progress.
        Returns True if OK to proceed, False if should pause.
        """
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Count experiments that have NOT reached qr_qa (final stage)
                cur.execute(f"""
                    SELECT COUNT(*) as in_progress_count
                    FROM {SCHEMA}.events e
                    WHERE e.event_type = 'experiment.started'
                      AND e.domain = %s
                      AND NOT EXISTS (
                          SELECT 1 FROM {SCHEMA}.event_processing ep 
                          WHERE ep.event_id = e.id AND ep.agent_name = 'qr_qa'
                            AND ep.processed_at IS NOT NULL
                      )
                """, (DOMAIN,))
                
                result = cur.fetchone()
                count = result['in_progress_count'] if result else 0
                
                if count > FLOOD_CONTROL_LIMIT:
                    self._log(f"Flood control: {count} experiments in progress (limit: {FLOOD_CONTROL_LIMIT}). Pausing.")
                    return False
                
                self._log(f"Flood control: {count} experiments in progress (limit: {FLOOD_CONTROL_LIMIT}). Proceeding.")
                return True
        finally:
            conn.close()
    
    def _get_experiment_count(self):
        """Get total count of experiment.started events for phase determination."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT COUNT(*) as count
                    FROM {SCHEMA}.events
                    WHERE event_type = 'experiment.started' AND domain = %s
                """, (DOMAIN,))
                result = cur.fetchone()
                return result['count'] if result else 0
        finally:
            conn.close()
    
    def _get_experiment_id_from_workflow(self, strategy_id: str) -> Optional[str]:
        """Get experiment_id from strategy_workflow table."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT experiment_id
                    FROM {SCHEMA}.strategy_workflow
                    WHERE strategy_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (strategy_id,))
                result = cur.fetchone()
                return result['experiment_id'] if result else None
        finally:
            conn.close()

    def _get_parent_param_set(self, experiment_id):
        """Recover param_set from parent experiment.started event."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                # Try looking up by event_id directly (experiment_id is the event UUID)
                cur.execute(f"""
                    SELECT payload_json,
                           payload_json->>'generation' as generation
                    FROM {SCHEMA}.events
                    WHERE event_type = 'experiment.started'
                      AND domain = %s
                      AND (id = %s OR payload_json->>'experiment_id' = %s)
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (DOMAIN, experiment_id, experiment_id))
                
                result = cur.fetchone()
                if result and result['payload_json']:
                    payload = result['payload_json'] if isinstance(result['payload_json'], dict) else json.loads(result['payload_json'])
                    
                    # Handle both wrapped (param_set) and flat payload formats
                    if 'param_set' in payload:
                        param_set = payload['param_set'] if isinstance(payload['param_set'], dict) else json.loads(payload['param_set'])
                    else:
                        # Flat format - extract param fields directly
                        param_set = {
                            'strategy_type': payload.get('strategy_type'),
                            'asset_universe': payload.get('asset_universe'),
                            'lookback_window': payload.get('lookback_window'),
                            'entry_threshold': payload.get('entry_threshold'),
                            'exit_threshold': payload.get('exit_threshold'),
                            'date_range': payload.get('date_range', {})
                        }
                    
                    generation = int(result['generation']) if result['generation'] else 1
                    return param_set, generation
                
                return None, 1
        finally:
            conn.close()
    
    def _create_strategy_workflow(self, strategy_id: str, experiment_id: str, param_set: dict, parent_experiment_id: str = None):
        """Create a strategy_workflow row for the new experiment."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                # Build strategy name from param_set
                strategy_type = param_set.get('strategy_type', 'unknown')
                asset_universe = param_set.get('asset_universe', [])
                # asset_universe is a list — join for display, use first ticker for category
                if isinstance(asset_universe, list):
                    asset_str = '_'.join(asset_universe[:3]).lower() if asset_universe else 'unknown'
                    category = asset_universe[0] if asset_universe else 'quant'
                else:
                    asset_str = str(asset_universe).replace(' ', '_').lower()
                    category = str(asset_universe)
                strategy_name = f"{strategy_type}_{asset_str}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
                
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.strategy_workflow
                        (strategy_id, name, status, category, auto_route, priority,
                         experiment_id, assigned_by, created_at, updated_at)
                    VALUES
                        (%s, %s, 'pending', %s, true, 50,
                         %s, 'qr_exp_manager', now(), now())
                """, (
                    strategy_id,
                    strategy_name,
                    category,
                    experiment_id
                ))
                conn.commit()
                self._log(f"Created strategy_workflow: {strategy_id} ({strategy_name})")
        finally:
            conn.close()

    def _generate_variants(self, param_set, experiment_id=None, parent_generation=0):
        """
        Generate 3 variant parameter sets from a base param_set.
        Phase 1 (<50 experiments): Each variant changes exactly one parameter.
        """
        variants = []
        
        # Define variation rules - each variant changes exactly ONE parameter
        variation_rules = [
            {'param': 'entry_threshold', 'multiplier': 1.25, 'description': 'increased_entry_threshold'},
            {'param': 'lookback_window', 'adder': 5, 'description': 'increased_lookback'},
            {'param': 'exit_threshold', 'multiplier': 0.5, 'description': 'decreased_exit_threshold'}
        ]
        
        for i, rule in enumerate(variation_rules):
            variant = copy.deepcopy(param_set)
            
            # Apply the single variation
            param_name = rule['param']
            if param_name in variant:
                original_value = variant[param_name]
                
                if 'multiplier' in rule:
                    variant[param_name] = round(original_value * rule['multiplier'], 6)
                elif 'adder' in rule:
                    variant[param_name] = original_value + rule['adder']
            
            variants.append({
                'param_set': variant,
                'parent_experiment_id': experiment_id,
                'generation': parent_generation + 1,
                'variant_description': rule['description']
            })
        
        return variants
    
    def _log_workflow_event(self, event_type, strategy_id, from_status, to_status, data):
        """Log to workflow_events."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.workflow_events
                        (event_type, agent, from_status, to_status, strategy_id, data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (event_type, AGENT_ID, from_status, to_status, 
                      strategy_id or 'exp_manager', json.dumps(data)))
            conn.commit()
        finally:
            conn.close()
    
    def _log(self, message):
        """Methodical, disciplined."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp}] ExpManager: {message}")


def main():
    """Run the Exp Manager agent."""
    agent = ExpManagerAgent()
    agent.run()


if __name__ == '__main__':
    main()
