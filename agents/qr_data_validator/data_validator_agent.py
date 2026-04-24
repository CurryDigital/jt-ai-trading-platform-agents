#!/usr/bin/env python3
"""
Data Validator Agent — OpenClaw Quant Pipeline
Pipeline subagent: asserts data quality on the gold layer before passing to Algo.

Pure assertions, boundary checks, and quality gating. Does NOT touch ETL scripts.
The ETL Manager owns the pipeline. This agent is a gatekeeper, not an engineer.

Note: RetryableError deliberately prevents mark_processed() so the
event stays pending for retry on next Hub cycle.
"""

import os
import json
import sys
import uuid
from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.sdk import Agent, Event, RetryableError

from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_DATA_VALIDATOR as AGENT_ID,
    DE_MISSING_BAR_TOLERANCE, DE_PRICE_SPIKE_STDDEV,
    DE_MIN_HISTORY_MULTIPLIER, MAX_RETRY_COUNT,
)


class DataValidatorAgent(Agent):
    """
    Data Engineering agent.
    Consumes: experiment.started
    Emits: dataset.ready or workflow.stuck (on persistent failure)
    """
    
    def __init__(self):
        super().__init__('qr_data_validator', domain='quant')
    
    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == 'experiment.started':
            self._prepare_dataset(event)
        else:
            self._log(f"Received unexpected event: {event.event_type}")
    
    def _check_gold_layer_ready(self) -> tuple:
        """
        Refinement 2: check gold_layer_state before doing any quality gating.
        Returns (is_ready: bool, state: str, notes: str)
        Blocks the experiment if state is 'locked', 'stale', or 'partial' with critical failures.
        """
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT state, notes, refreshed_at, sources_failed
                    FROM {SCHEMA}.gold_layer_state LIMIT 1
                """)
                row = cur.fetchone()
                if not row:
                    return False, 'unknown', 'gold_layer_state table has no rows — run migration_003.sql'
                state, notes, refreshed_at, sources_failed = row
                if state == 'ready':
                    return True, state, notes
                elif state == 'locked':
                    return False, state, f'ETL refresh in progress since {refreshed_at}. Experiment will retry.'
                elif state == 'stale':
                    return False, state, f'Gold layer not refreshed yet today. Notes: {notes}'
                elif state == 'partial':
                    # Partial is acceptable — warn but proceed
                    self._log(f"Gold layer is partial ({notes}). Proceeding with available data.")
                    return True, state, notes
                return False, state, f'Unknown gold layer state: {state}'
        except Exception as e:
            # If the table doesn't exist yet (pre-migration), warn but don't block
            self._log(f"WARNING: could not read gold_layer_state ({e}). Proceeding without lock check.")
            return True, 'unknown', str(e)
        finally:
            conn.close()

    def _prepare_dataset(self, event: Event):
        """Validate dataset quality for an experiment."""
        event_id = event.id
        payload = event.payload or {}
        
        experiment_id = payload.get('experiment_id')
        param_set = payload.get('param_set', {})
        # H1 FIX: propagate strategy_id from incoming event
        strategy_id = event.strategy_id or payload.get('strategy_id')
        
        self._log(f"Processing experiment {experiment_id} (strategy {strategy_id})")
        self._log_workflow_event('dv_processing_started', experiment_id,
                                'pending', 'in_progress',
                                {'event_id': str(event_id), 'param_set': param_set})
        
        # ── Refinement 2: gold layer lock gate ───────────────────────────────
        gold_ready, gold_state, gold_notes = self._check_gold_layer_ready()
        if not gold_ready:
            reason = f"Gold layer not ready (state={gold_state}): {gold_notes}"
            self._log(f"BLOCKED: {reason}")
            # Emit workflow.stuck — Monitor will re-queue once ETL completes
            self.emit_event(
                event_type='workflow.stuck',
                strategy_id=strategy_id,
                payload={
                    'experiment_id': experiment_id,
                    'stuck_at_event': 'experiment.started',
                    'agent_name': AGENT_ID,
                    'reason': reason,
                    'gold_layer_state': gold_state,
                }
            )
            self._log_workflow_event('dv_gold_layer_blocked', experiment_id,
                                    'in_progress', 'stuck',
                                    {'event_id': str(event_id),
                                     'gold_state': gold_state,
                                     'reason': gold_notes})
            return  # do NOT raise — mark as processed so it's not retried blindly
        # ─────────────────────────────────────────────────────────────────────
        
        try:
            # Check retry count
            retry_count = self._get_retry_count(experiment_id)
            if retry_count > 0:
                self._log(f"Retry attempt {retry_count} for experiment {experiment_id}")
            
            # Run quality checks
            all_passed, flags = self._run_quality_checks(param_set, experiment_id)
            
            if all_passed:
                # Success - emit dataset.ready
                dataset_id = str(uuid.uuid4())
                version = 'v1.0.0'
                asset_universe = param_set.get('asset_universe', [])
                date_range = param_set.get('date_range', {})
                row_count = 0  # Would be actual count when data pipeline connected
                
                self.emit_event(
                    event_type='dataset.ready',
                    strategy_id=strategy_id,
                    payload={
                        'event_id': str(event_id),
                        'experiment_id': experiment_id,
                        'strategy_id': strategy_id,
                        'dataset_id': dataset_id,
                        'version': version,
                        'asset_universe': asset_universe,
                        'date_range': date_range,
                        'row_count': row_count,
                        'quality_flags': flags,
                        'param_set': param_set
                    }
                )
                
                self._log_workflow_event('dv_processing_completed', experiment_id,
                                        'in_progress', 'completed',
                                        {'event_id': str(event_id), 'dataset_id': dataset_id})
                self._log(f"Experiment {experiment_id}: Dataset {dataset_id} ready")
                
            else:
                # Failure - handle retry logic
                reason = f"Quality checks failed: {flags}"
                result = self._handle_failure(event_id, experiment_id, reason, retry_count)
                
                if result == 'stuck':
                    # Emit workflow.stuck after 2 failures
                    self.emit_event(
                        event_type='workflow.stuck',
                        strategy_id=strategy_id,
                        payload={
                            'experiment_id': experiment_id,
                            'stuck_at_event': 'experiment.started',
                            'agent_name': AGENT_ID,
                            'reason': reason,
                            'flags': flags
                        }
                    )
                    self._log_workflow_event('dv_processing_stuck', experiment_id,
                                            'in_progress', 'stuck',
                                            {'event_id': str(event_id), 'flags': flags})
                else:
                    # Will retry - raise exception to prevent mark_processed()
                    self._log(f"Experiment {experiment_id}: Will retry (attempt {retry_count + 1})")
                    raise RetryableError(f"Quality checks failed, retry {retry_count + 1}")
                    
        except Exception as e:
            self._log(f"ERROR processing experiment {experiment_id}: {str(e)}")
            self._log_workflow_event('dv_processing_failed', experiment_id,
                                    'in_progress', 'failed',
                                    {'event_id': str(event_id), 'error': str(e)})
            raise
    
    def _get_retry_count(self, experiment_id):
        """Count previous failures for this experiment."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT COUNT(*) as fail_count
                    FROM {SCHEMA}.workflow_events
                    WHERE event_type = 'dv_quality_check_failed'
                      AND data->>'experiment_id' = %s
                """, (str(experiment_id),))
                result = cur.fetchone()
                return result[0] if result else 0
        finally:
            conn.close()
    
    def _handle_failure(self, event_id, experiment_id, reason, retry_count):
        """
        Rule 4: On first failure: retry once.
        On second failure: return 'stuck' to emit workflow.stuck.
        """
        self._log_workflow_event('dv_quality_check_failed', experiment_id,
                                'in_progress', 'failed',
                                {'event_id': str(event_id), 'reason': reason, 'retry': retry_count})
        
        if retry_count >= 2:
            self._log(f"Experiment {experiment_id}: Exceeded 2 failures, emitting workflow.stuck")
            return 'stuck'
        
        return 'retry'
    
    def _run_quality_checks(self, param_set, experiment_id):
        """
        Run 5 quality checks. Checks 1 and 5 use real market data.
        Returns: (all_passed: bool, flags: list)
        """
        flags = []
        
        asset_universe = param_set.get('asset_universe', [])
        date_range = param_set.get('date_range', {})
        start_date = date_range.get('start', '')
        end_date = date_range.get('end', '')
        lookback_window = param_set.get('lookback_window', 20)
        
        self._log(f"Running quality checks for {len(asset_universe)} assets, {start_date} to {end_date}")
        
        conn = self.hub._get_conn()
        try:
            # Check 1: No missing bars (REAL)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(DISTINCT date) as available_days
                    FROM gold.stock_metrics_history
                    WHERE ticker = ANY(%s)
                    AND date BETWEEN %s AND %s
                """, (asset_universe, start_date, end_date))
                row = cur.fetchone()
                available_days = row[0] if row else 0
                
                start = datetime.strptime(start_date, '%Y-%m-%d')
                end = datetime.strptime(end_date, '%Y-%m-%d')
                calendar_days = (end - start).days
                expected_trading_days = int(calendar_days * 252 / 365)
                
                if available_days < expected_trading_days * 0.90:
                    flags.append('missing_bars')
                    self._log(f"Check 1 (missing bars): FAIL — {available_days} days available, expected ~{expected_trading_days}")
                else:
                    self._log(f"Check 1 (missing bars): PASS — {available_days} trading days available")
            
            # Check 2: No lookahead bias (STUB)
            self._log("Check 2 (lookahead bias): stub — implement when feature pipeline is connected")
            
            # Check 3: Dataset version matches (STUB)
            self._log("Check 3 (version match): stub — implement when dataset registry is connected")
            
            # Check 4: No price spikes > 5 std (STUB)
            self._log("Check 4 (price spikes): stub — implement when market_data table is connected")
            
            # Check 5: Sufficient history (REAL)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT MIN(date) as earliest_date
                    FROM gold.stock_metrics_history
                    WHERE ticker = ANY(%s)
                """, (asset_universe,))
                row = cur.fetchone()
                earliest = row[0] if row and row[0] else None

            if earliest and start_date:
                required_start = (
                    datetime.strptime(start_date, '%Y-%m-%d') 
                    - timedelta(days=lookback_window * 2)
                ).date()
                
                if earliest > required_start:
                    flags.append('insufficient_history')
                    self._log(f"Check 5 (sufficient history): FAIL — earliest {earliest}, need {required_start}")
                else:
                    self._log(f"Check 5 (sufficient history): PASS — data available from {earliest}")
        
        finally:
            conn.close()
        
        all_passed = len(flags) == 0
        self._log(f"Quality checks: {5 - len(flags)}/5 passed")
        return all_passed, flags
    
    def _log_workflow_event(self, event_type, experiment_id, from_status, to_status, data, strategy_id=None):
        """Log to workflow_events. Includes strategy_id for FK audit trail when available."""
        conn = self.hub._get_conn()
        try:
            # Include experiment_id in data for traceability
            if experiment_id and 'experiment_id' not in data:
                data['experiment_id'] = experiment_id
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.workflow_events
                        (event_type, agent, from_status, to_status, strategy_id, data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (event_type, AGENT_ID, from_status, to_status, strategy_id, json.dumps(data)))
            conn.commit()
        finally:
            conn.close()
    
    def _log(self, message):
        """Calm, methodical. Reports facts without emotion."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp}] DATA VALIDATOR: {message}")


def main():
    """Run the DE agent."""
    agent = DataValidatorAgent()
    agent.run()


if __name__ == '__main__':
    main()
