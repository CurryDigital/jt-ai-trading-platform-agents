#!/usr/bin/env python3
"""
Algo Agent (Hub-based) — OpenClaw Quant Pipeline.
Pipeline subagent: runs backtest, persists trade ledger + summary metrics,
emits backtest.completed.

The contract lives in agents/qr_algo/AGENTS.md. The backtest math lives in
agents/qr_algo/backtest.py. This file is the orchestration glue: pull events,
call run_backtest, persist results in the right order, emit.
"""

import json
import sys
from datetime import datetime
from typing import Any, Dict, Iterable

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.sdk import Agent, Event

from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_ALGO as AGENT_ID,
    BACKTEST_TIMEOUT_MINUTES,
)
from agents.qr_algo import backtest as bt
from agents.qr_algo.backtest import (
    Trade, UnsupportedStrategyError, InsufficientDataError,
)


BACKTEST_ENGINE_VERSION = "v2.0.0-stdlib"


class AlgoAgent(Agent):
    """
    Backtest engine.
    Consumes: dataset.ready
    Emits:    backtest.completed | workflow.stuck (on unsupported strategy / no data)
    """

    def __init__(self):
        super().__init__('qr_algo', domain='quant')

    def on_event(self, event: Event):
        if event.event_type == 'dataset.ready':
            self._run_backtest(event)
        else:
            self._log(f"Received unexpected event: {event.event_type}")

    def _run_backtest(self, event: Event):
        event_id = event.id
        payload = event.payload or {}
        experiment_id = payload.get('experiment_id')
        dataset_id = payload.get('dataset_id')
        param_set = payload.get('param_set', {}) or {}
        strategy_id = event.strategy_id or payload.get('strategy_id')
        strategy_type = param_set.get('strategy_type', 'unknown')

        self._log(
            f"Backtest start: strategy={strategy_id} type={strategy_type} "
            f"dataset={dataset_id}"
        )

        # Ensure the workflow row exists so the trade ledger FK has somewhere to land.
        self._upsert_strategy_workflow(strategy_id, experiment_id, dataset_id, metrics={})
        self._log_workflow_event(
            'backtest_started', strategy_id, 'pending', 'in_progress',
            {'event_id': str(event_id), 'experiment_id': experiment_id,
             'dataset_id': dataset_id, 'strategy_type': strategy_type},
        )

        start_wall = datetime.utcnow()
        try:
            trades, metrics, status = self._execute(param_set)
        except UnsupportedStrategyError as e:
            self._stuck(strategy_id, event_id, experiment_id,
                        reason=f"unsupported_strategy_type:{strategy_type}", detail=str(e))
            return
        except InsufficientDataError as e:
            self._stuck(strategy_id, event_id, experiment_id,
                        reason='insufficient_data', detail=str(e))
            return
        except Exception as e:
            self._log(f"ERROR backtesting {strategy_id}: {e}")
            self._log_workflow_event(
                'backtest_failed', strategy_id, 'in_progress', 'failed',
                {'event_id': str(event_id), 'error': str(e)},
            )
            raise

        elapsed_minutes = (datetime.utcnow() - start_wall).total_seconds() / 60.0

        # Trade ledger commits FIRST so qr_qa Gate 0 can verify against it.
        self._persist_trades(strategy_id, trades)
        # Then summary metrics.
        self._upsert_strategy_workflow(strategy_id, experiment_id, dataset_id, metrics)

        if elapsed_minutes > BACKTEST_TIMEOUT_MINUTES:
            status = 'timeout'
            self._log(f"Strategy {strategy_id}: TIMEOUT after {elapsed_minutes:.1f} min")
        else:
            self._log(
                f"BACKTESTED {strategy_id}: "
                f"sharpe_oos={metrics['sharpe_oos']:.2f} "
                f"dd={metrics['max_drawdown']:.2%} "
                f"trades={metrics['trade_count_is']}+{metrics['trade_count_oos']} "
                f"in {elapsed_minutes:.1f}m"
            )

        self.emit_event(
            event_type='backtest.completed',
            strategy_id=strategy_id,
            payload={
                'event_id':                str(event_id),
                'experiment_id':           experiment_id,
                'strategy_id':             strategy_id,
                'dataset_id':              dataset_id,
                'metrics':                 metrics,
                'status':                  status,
                'backtest_engine_version': BACKTEST_ENGINE_VERSION,
            },
        )

        self._log_workflow_event(
            'backtest_completed', strategy_id, 'in_progress', 'completed',
            {'event_id': str(event_id), 'strategy_id': strategy_id,
             'status': status, 'elapsed_min': round(elapsed_minutes, 2)},
        )

    # ── work ───────────────────────────────────────────────────────────────

    def _execute(self, param_set: Dict[str, Any]):
        """Open a connection just for the backtest read; close in finally."""
        conn = self.hub._get_conn()
        try:
            return bt.run_backtest(conn, param_set)
        finally:
            conn.close()

    def _persist_trades(self, strategy_id: str, trades: Iterable[Trade]) -> None:
        """Bulk-insert the trade ledger. MUST commit before metrics."""
        rows = [t.as_db_row(strategy_id) for t in trades]
        if not rows:
            self._log(f"No trades produced for {strategy_id}; metrics will reflect empty ledger.")
            return
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.executemany(
                    f"""
                    INSERT INTO {SCHEMA}.strategy_backtest_trades
                      (strategy_id, ticker, period_type, entry_date, exit_date,
                       entry_price, exit_price, pnl_pct, holding_days, exit_reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    rows,
                )
            conn.commit()
            self._log(f"Persisted {len(rows)} trades for strategy {strategy_id}")
        finally:
            conn.close()

    def _upsert_strategy_workflow(self, strategy_id, experiment_id, dataset_id, metrics):
        """Create or update strategy_workflow row."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.strategy_workflow
                      (strategy_id, name, status, experiment_id, dataset_id, metrics, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (strategy_id) DO UPDATE SET
                        metrics       = EXCLUDED.metrics,
                        experiment_id = EXCLUDED.experiment_id,
                        dataset_id    = EXCLUDED.dataset_id,
                        updated_at    = CURRENT_TIMESTAMP
                    """,
                    (strategy_id, f"strategy-{(strategy_id or '')[:8]}", 'pending',
                     experiment_id, dataset_id, json.dumps(metrics)),
                )
            conn.commit()
        finally:
            conn.close()

    # ── failure path ───────────────────────────────────────────────────────

    def _stuck(self, strategy_id, event_id, experiment_id, *, reason: str, detail: str):
        """Emit workflow.stuck and bail. qr_monitor + qr_idea_intake handle the rest."""
        self._log(f"STUCK {strategy_id}: {reason} ({detail})")
        self.emit_event(
            event_type='workflow.stuck',
            strategy_id=strategy_id,
            payload={
                'workflow_id':    strategy_id,
                'experiment_id':  experiment_id,
                'stuck_at_event': 'dataset.ready',
                'agent_name':     AGENT_ID,
                'reason':         reason,
                'detail':         detail,
                'event_id':       str(event_id),
            },
        )
        self._log_workflow_event(
            'backtest_stuck', strategy_id, 'in_progress', 'stuck',
            {'event_id': str(event_id), 'reason': reason, 'detail': detail},
        )

    # ── audit log ──────────────────────────────────────────────────────────

    def _log_workflow_event(self, event_type, strategy_id, from_status, to_status, data):
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    INSERT INTO {SCHEMA}.workflow_events
                      (event_type, agent, from_status, to_status, strategy_id, data)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (event_type, AGENT_ID, from_status, to_status,
                     data.get('strategy_id', strategy_id), json.dumps(data)),
                )
            conn.commit()
        finally:
            conn.close()

    def _log(self, message):
        timestamp = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp}] Algo: {message}", flush=True)


def main():
    AlgoAgent().run()


if __name__ == '__main__':
    main()
