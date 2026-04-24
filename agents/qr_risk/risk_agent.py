#!/usr/bin/env python3
"""
Risk Agent (Hub-based) - OpenClaw Quant Pipeline
Pipeline subagent: evaluates backtest results for risk violations.
 
Uses hub.sdk.Agent base class for event-driven architecture.
"""
 
import os
import json
import sys
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor
 
sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.sdk import Agent, Event
 
from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_RISK as AGENT_ID,
    RISK_APPROVAL_THRESHOLD, RISK_BORDERLINE_THRESHOLD,
    RISK_WEIGHT_MAX_DRAWDOWN, RISK_WEIGHT_SHARPE_OOS,
    RISK_WEIGHT_SHARPE_RATIO, RISK_WEIGHT_HIGH_TURNOVER,
    RISK_WEIGHT_LOW_TRADE_COUNT,
)
from agents.shared.threshold import check_threshold
 
 
class RiskAgent(Agent):
    """
    Risk evaluation agent.
    Consumes: backtest.completed
    Emits: risk.evaluated
    """
    
    def __init__(self):
        super().__init__('qr_risk', domain='quant')
    
    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == 'backtest.completed':
            self._evaluate_risk(event)
        else:
            self._log(f"Received unexpected event: {event.event_type}")
    
    def _evaluate_risk(self, event: Event):
        """Evaluate risk for a completed backtest."""
        # Extract data from event
        event_id = event.id
        strategy_id = event.strategy_id
        payload = event.payload
        
        experiment_id = payload.get('experiment_id') if payload else None
        metrics = payload.get('metrics') if payload else {}
        
        self._log(f"Evaluating strategy {strategy_id}")
        self._log_workflow_event('risk_evaluation_started', strategy_id,
                                'pending', 'in_progress',
                                {'event_id': str(event_id), 'experiment_id': experiment_id})
        
        try:
            # Load thresholds using hub connection
            thresholds = self._load_risk_thresholds()
            if not thresholds:
                self._log("WARNING: No risk thresholds loaded")
                return
            
            # Evaluate risk
            risk_result = self._evaluate_risk_logic(metrics, thresholds, strategy_id)
            
            # Update strategy_workflow with risk results
            self._update_strategy_workflow(strategy_id, risk_result)
            
            # Emit risk.evaluated event via SDK
            self.emit_event(
                event_type='risk.evaluated',
                strategy_id=strategy_id,
                payload={
                    'event_id': str(event_id),
                    'strategy_id': strategy_id,
                    'experiment_id': experiment_id,
                    'risk_score': risk_result['score'],
                    'risk_flags': risk_result['flags'],
                    'risk_approved': risk_result['approved'],
                    'risk_notes': risk_result['notes']
                }
            )
            
            # SDK calls mark_processed() automatically after on_event() returns
            
            self._log_workflow_event('risk_evaluation_completed', strategy_id,
                                    'in_progress', 'completed',
                                    {'event_id': str(event_id), 
                                     'score': risk_result['score'],
                                     'flags': risk_result['flags'], 
                                     'approved': risk_result['approved']})
            
            status_str = "APPROVED" if risk_result['approved'] else "REJECTED"
            self._log(f"Strategy {strategy_id}: {status_str} with score {risk_result['score']}")
            
        except Exception as e:
            self._log(f"ERROR evaluating strategy {strategy_id}: {str(e)}")
            self._log_workflow_event('risk_evaluation_failed', strategy_id,
                                    'in_progress', 'failed',
                                    {'event_id': str(event_id), 'error': str(e)})
            raise
    
    def _load_risk_thresholds(self):
        """Load risk thresholds from risk_config at runtime."""
        thresholds = {}
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT name, value, operator, description
                    FROM {SCHEMA}.risk_config
                    WHERE enabled = true AND name NOT LIKE 'qa_%%'
                """)
                for row in cur.fetchall():
                    thresholds[row['name']] = {
                        'value': row['value'],
                        'operator': row['operator'],
                        'description': row['description']
                    }
            self._log(f"Loaded {len(thresholds)} risk thresholds")
            return thresholds
        finally:
            conn.close()
    
    def _evaluate_risk_logic(self, metrics, thresholds, strategy_id):
        """Evaluate 6 risk checks. Returns {score, flags, approved, notes}."""
        flags = []
        notes = []
        
        def get(m, d=0.0):
            return metrics.get(m, d) if isinstance(metrics, dict) else d
        
        # 1. high_drawdown: max_drawdown > threshold
        if 'high_drawdown' in thresholds:
            t = thresholds['high_drawdown']
            max_dd = get('max_drawdown', 0.0)
            if check_threshold(max_dd, t['operator'], t['value']):
                flags.append('high_drawdown')
                notes.append(f"max_drawdown {max_dd:.2f} exceeds threshold {t['value']:.2f}")
                self._log(f"Strategy {strategy_id}: max_drawdown {max_dd:.2f} exceeds threshold {t['value']:.2f}. Flagged: high_drawdown.")
        
        # 2. low_sharpe_oos: sharpe_oos < threshold
        if 'low_sharpe_oos' in thresholds:
            t = thresholds['low_sharpe_oos']
            sharpe = get('sharpe_oos', 0.0)
            if check_threshold(sharpe, t['operator'], t['value']):
                flags.append('low_sharpe_oos')
                notes.append(f"sharpe_oos {sharpe:.2f} below threshold {t['value']:.2f}")
                self._log(f"Strategy {strategy_id}: sharpe_oos {sharpe:.2f} below threshold {t['value']:.2f}. Flagged: low_sharpe_oos.")
        
        # 3. concentration_risk: single asset exposure > threshold
        if 'concentration_risk' in thresholds:
            t = thresholds['concentration_risk']
            exposure = get('max_single_asset_exposure', get('concentration_risk', 0.0))
            if check_threshold(exposure, t['operator'], t['value']):
                flags.append('concentration_risk')
                notes.append(f"single asset exposure {exposure:.2f} exceeds threshold {t['value']:.2f}")
                self._log(f"Strategy {strategy_id}: single asset exposure {exposure:.2f} exceeds threshold {t['value']:.2f}. Flagged: concentration_risk.")
        
        # 4. overfitting_signal: sharpe_ratio_is_oos < threshold
        if 'overfitting_signal' in thresholds:
            t = thresholds['overfitting_signal']
            ratio = get('sharpe_ratio_is_oos', 0.0)
            if check_threshold(ratio, t['operator'], t['value']):
                flags.append('overfitting_signal')
                notes.append(f"IS/OOS Sharpe ratio {ratio:.2f} below threshold {t['value']:.2f}")
                self._log(f"Strategy {strategy_id}: IS/OOS Sharpe ratio {ratio:.2f} below threshold {t['value']:.2f}. Flagged: overfitting_signal.")
        
        # 5. low_trade_count: trade_count_oos < threshold
        if 'low_trade_count' in thresholds:
            t = thresholds['low_trade_count']
            count = get('trade_count_oos', 0)
            if check_threshold(count, t['operator'], t['value']):
                flags.append('low_trade_count')
                notes.append(f"trade_count_oos {count} below threshold {t['value']}")
                self._log(f"Strategy {strategy_id}: trade_count_oos {count} below threshold {t['value']}. Flagged: low_trade_count.")
        
        # 6. tail_risk: cvar > threshold
        if 'tail_risk' in thresholds:
            t = thresholds['tail_risk']
            cvar = get('cvar', get('cvar_95', 0.0))
            if check_threshold(cvar, t['operator'], t['value']):
                flags.append('tail_risk')
                notes.append(f"CVaR {cvar:.4f} exceeds threshold {t['value']:.4f}")
                self._log(f"Strategy {strategy_id}: CVaR {cvar:.4f} exceeds threshold {t['value']:.4f}. Flagged: tail_risk.")
        
        approved = len(flags) == 0
        
        return {
            'score': round(len(flags) / 6, 2),
            'flags': flags,
            'approved': approved,
            'notes': '; '.join(notes) if notes else 'All checks passed.'
        }
    
    def _update_strategy_workflow(self, strategy_id, risk_result):
        """Write risk results to strategy_workflow."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.strategy_workflow
                    SET risk_score = %s,
                        risk_flags = %s,
                        risk_approved = %s,
                        risk_notes = %s,
                        risk_evaluated_at = CURRENT_TIMESTAMP
                    WHERE strategy_id = %s
                """, (
                    risk_result['score'],
                    json.dumps(risk_result['flags']),
                    risk_result['approved'],
                    risk_result['notes'],
                    strategy_id
                ))
            conn.commit()
            self._log(f"Updated strategy_workflow for {strategy_id}: score={risk_result['score']}, approved={risk_result['approved']}")
        finally:
            conn.close()
    
    def _log_workflow_event(self, event_type, strategy_id, from_status, to_status, data):
        """Log to workflow_events."""
        conn = self.hub._get_conn()
        try:
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
        """The skeptic. Defaults to caution."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp}] Risk: {message}")
 
 
def main():
    """Run the Risk agent."""
    agent = RiskAgent()
    agent.run()
 
 
if __name__ == '__main__':
    main()
 
