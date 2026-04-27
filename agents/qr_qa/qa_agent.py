#!/usr/bin/env python3
"""
QA Agent (Hub-based) - OpenClaw Quant Pipeline
Pipeline subagent: quality gatekeeper, checks risk clearance + statistical thresholds.

Uses hub.sdk.Agent base class for event-driven architecture.
"""

import os
import json
import sys
import uuid
from datetime import datetime, timezone
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.sdk import Agent, Event

from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_QA as AGENT_ID,
)
from agents.shared.threshold import check_threshold


class QAAgent(Agent):
    """
    QA evaluation agent.
    Consumes: risk.evaluated
    Emits: qa.validated
    """

    def __init__(self):
        super().__init__('qr_qa', domain='quant')

    def on_event(self, event: Event):
        """Process incoming events."""
        if event.event_type == 'risk.evaluated':
            self._evaluate_qa(event)
        else:
            self._log(f"Received unexpected event: {event.event_type}")

    def _evaluate_qa(self, event: Event):
        """Evaluate QA gates for a risk-evaluated strategy."""
        event_id = event.id
        strategy_id = event.strategy_id
        risk_payload = event.payload or {}

        experiment_id = risk_payload.get('experiment_id')

        self._log(f"Evaluating strategy {strategy_id}")
        self._log_workflow_event('qa_evaluation_started', strategy_id,
                                'pending', 'in_progress',
                                {'event_id': str(event_id), 'experiment_id': experiment_id})

        try:
            # Gate 1: Risk clearance (before any DB query)
            if not risk_payload.get('risk_approved', False):
                gate_result = {
                    'passed': False,
                    'failed_gate': 1,
                    'rejection_reason': f"Risk rejected strategy. Risk score: {risk_payload.get('risk_score', 'N/A')}"
                }
                self._log(f"Strategy {strategy_id}: Failed gate 1 - Risk not approved")
                self._emit_qa_rejection(event_id, strategy_id, experiment_id, gate_result)
                self._log_workflow_event('qa_evaluation_completed', strategy_id,
                                        'in_progress', 'completed',
                                        {'event_id': str(event_id), 'result': 'rejected', 'gate': 1})
                return

            # Gate 1 passed - load QA thresholds
            thresholds = self._load_qa_thresholds()
            if not thresholds:
                self._log(f"WARNING: No QA thresholds loaded for strategy {strategy_id}")
                return

            # Fetch metrics from strategy_workflow
            metrics = self._get_metrics(strategy_id)

            # Evaluate gates 2-5
            gate_result = self._evaluate_qa_gates(risk_payload, metrics, thresholds, strategy_id)

            # Handle result
            if gate_result['passed']:
                # ON PASS: Write lineage + emit event atomically (single transaction)
                self._write_lineage_and_emit(
                    event_id, strategy_id, experiment_id, metrics,
                    risk_payload.get('risk_score', 0.0),
                    risk_payload.get('param_set', {}),
                    gate_result
                )
                self._log(f"Strategy {strategy_id}: promoted and notified.")
            else:
                # ON FAIL: Just emit rejection (no lineage write)
                self._emit_qa_rejection(event_id, strategy_id, experiment_id, gate_result)
                self._log(f"Strategy {strategy_id}: {gate_result['rejection_reason']}")

            self._log_workflow_event('qa_evaluation_completed', strategy_id,
                                    'in_progress', 'completed',
                                    {'event_id': str(event_id),
                                     'result': 'passed' if gate_result['passed'] else 'rejected',
                                     'gate': gate_result['failed_gate']})

        except Exception as e:
            self._log(f"ERROR evaluating strategy {strategy_id}: {str(e)}")
            self._log_workflow_event('qa_evaluation_failed', strategy_id,
                                    'in_progress', 'failed',
                                    {'event_id': str(event_id), 'error': str(e)})
            raise

    def _load_qa_thresholds(self):
        """Load QA thresholds from risk_config."""
        thresholds = {}
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT name, value, operator, description
                    FROM {SCHEMA}.risk_config
                    WHERE enabled = true AND name LIKE 'qa_%%'
                    ORDER BY name
                """)
                for row in cur.fetchall():
                    thresholds[row['name']] = {
                        'value': row['value'],
                        'operator': row['operator'],
                        'description': row['description']
                    }
            self._log(f"Loaded {len(thresholds)} QA thresholds")
            return thresholds
        finally:
            conn.close()

    def _get_metrics(self, strategy_id):
        """Fetch metrics from strategy_workflow."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT metrics FROM {SCHEMA}.strategy_workflow
                    WHERE strategy_id = %s
                """, (strategy_id,))
                row = cur.fetchone()

            metrics = row['metrics'] if row else {}
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            return metrics
        finally:
            conn.close()

    def _evaluate_qa_gates(self, risk_payload, metrics, thresholds, strategy_id):
        """Evaluate 5 quality gates in strict order, stop at first fail."""
        def get(m, d=0.0):
            return metrics.get(m, d) if isinstance(metrics, dict) else d

        # Gate 1: Risk clearance (already checked before this call)

        # Gate 2: sharpe_oos — uses operator from risk_config (e.g. 'lt' means fail if below)
        if 'qa_min_sharpe_oos' in thresholds:
            t = thresholds['qa_min_sharpe_oos']
            sharpe = get('sharpe_oos', 0.0)
            if check_threshold(sharpe, t['operator'], t['value']):
                return {
                    'passed': False,
                    'failed_gate': 2,
                    'rejection_reason': f"Failed gate 2: sharpe_oos {sharpe:.2f} vs threshold {t['value']:.2f} (op: {t['operator']}). Recommend improving signal quality."
                }

        # Gate 3: max_drawdown — uses operator from risk_config (e.g. 'gt' means fail if exceeds)
        if 'qa_max_drawdown' in thresholds:
            t = thresholds['qa_max_drawdown']
            max_dd = abs(get('max_drawdown', 1.0))
            if check_threshold(max_dd, t['operator'], t['value']):
                return {
                    'passed': False,
                    'failed_gate': 3,
                    'rejection_reason': f"Failed gate 3: |max_drawdown| {max_dd:.2f} vs threshold {t['value']:.2f} (op: {t['operator']}). Recommend reducing position sizing."
                }

        # Gate 4: trade_count_oos — uses operator from risk_config (e.g. 'lt' means fail if below)
        if 'qa_min_trade_count_oos' in thresholds:
            t = thresholds['qa_min_trade_count_oos']
            count = get('trade_count_oos', 0)
            if check_threshold(count, t['operator'], t['value']):
                return {
                    'passed': False,
                    'failed_gate': 4,
                    'rejection_reason': f"Failed gate 4: trade_count_oos {count} vs threshold {t['value']} (op: {t['operator']}). Recommend longer backtest period."
                }

        # Gate 5: sharpe_ratio_is_oos — uses operator from risk_config (e.g. 'lt' means fail if below)
        if 'qa_min_sharpe_ratio_is_oos' in thresholds:
            t = thresholds['qa_min_sharpe_ratio_is_oos']
            ratio = get('sharpe_ratio_is_oos', 0.0)
            if check_threshold(ratio, t['operator'], t['value']):
                return {
                    'passed': False,
                    'failed_gate': 5,
                    'rejection_reason': f"Failed gate 5: IS/OOS Sharpe ratio {ratio:.2f} vs threshold {t['value']:.2f} (op: {t['operator']}). Likely overfitting."
                }

        return {'passed': True, 'failed_gate': None, 'rejection_reason': None}

    def _write_lineage_and_emit(self, event_id, strategy_id, experiment_id, metrics, risk_score, param_set, gate_result):
        """
        Atomicity contract (DO NOT split this method):
            ONE connection. ONE cursor block. TWO INSERTs. ONE commit().
        If lineage is written but qa.validated is not emitted (or vice versa),
        the operator's MTBF for "promoted but no event" goes from 0 to ∞.
        Postgres' transactional guarantee is doing the work; the code below
        only has to keep both writes inside one BEGIN..COMMIT.

        Defensive guards (Tier 3 resilience):
          1. After conn.commit(), verify cur.connection IS conn — catches any
             future refactor that accidentally splits the cursor onto a
             different connection.
          2. The exception path explicitly rolls back; no half-committed state.
        See agents/qr_qa/test_qa_atomicity.py for the regression test that
        enforces this contract.
        """
        conn = self.hub._get_conn()
        source_event_id = event_id  # propagated into both rows for traceability
        new_event_id = str(uuid.uuid4())
        try:
            with conn.cursor() as cur:
                # GUARD: cursor must be bound to the connection we opened above.
                # If a future refactor accidentally uses a different cursor or
                # connection, this assertion fires before we commit anything.
                assert cur.connection is conn, (
                    "QA atomicity violation: cursor bound to different connection. "
                    "Both INSERTs must run on the same conn for the lineage + "
                    "qa.validated promotion to be atomic."
                )

                # 1. Write to strategy_lineage.
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.strategy_lineage
                        (strategy_id, experiment_id, dataset_version, backtest_engine_version,
                         strategy_parameters, result_metrics, source_event_id,
                         sharpe_oos, max_drawdown, trade_count_oos, risk_score, param_set, promoted_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                """, (
                    strategy_id, experiment_id, 'v1.0.0', 'v1.0.0',
                    json.dumps(param_set) if param_set else '{}',
                    json.dumps(metrics) if metrics else '{}',
                    source_event_id,
                    metrics.get('sharpe_oos'), metrics.get('max_drawdown'),
                    metrics.get('trade_count_oos'), risk_score,
                    json.dumps(param_set) if param_set else None
                ))

                # 2. Insert qa.validated event directly (SAME cursor, same txn).
                payload = {
                    'event_id': str(event_id),
                    'strategy_id': strategy_id,
                    'experiment_id': experiment_id,
                    'passed': True,
                    'failed_gate': None,
                    'rejection_reason': None,
                    'promoted_to_lineage': True,
                    'metrics_summary': {
                        'sharpe_oos': metrics.get('sharpe_oos'),
                        'max_drawdown': metrics.get('max_drawdown'),
                        'trade_count_oos': metrics.get('trade_count_oos')
                    }
                }
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.events
                        (id, event_type, domain, strategy_id, payload_json, source_agent, status)
                    VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                """, (
                    new_event_id, 'qa.validated', DOMAIN,
                    strategy_id, json.dumps(payload), AGENT_ID
                ))

            # Single commit — the only one in this method.
            conn.commit()
            self._log(
                f"Strategy {strategy_id}: lineage written and qa.validated emitted "
                f"atomically (event {new_event_id}, source_event_id {source_event_id})"
            )
            return new_event_id

        except Exception:
            conn.rollback()
            self._log(f"Strategy {strategy_id}: lineage+event ROLLBACK due to exception")
            raise
        finally:
            conn.close()

    def _emit_qa_rejection(self, event_id, strategy_id, experiment_id, gate_result):
        """Emit qa.validated (failed) event via SDK. Rejections don't touch lineage."""
        payload = {
            'event_id': str(event_id),
            'strategy_id': strategy_id,
            'experiment_id': experiment_id,
            'passed': False,
            'failed_gate': gate_result['failed_gate'],
            'rejection_reason': gate_result['rejection_reason'],
            'promoted_to_lineage': False
        }
        self.emit_event(
            event_type='qa.validated',
            strategy_id=strategy_id,
            payload=payload
        )

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
        """The gatekeeper. Unemotional."""
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp}] QA: {message}")


def main():
    """Run the QA agent."""
    agent = QAAgent()
    agent.run()


if __name__ == '__main__':
    main()
