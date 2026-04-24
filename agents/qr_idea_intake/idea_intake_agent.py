#!/usr/bin/env python3
"""
Idea Intake Agent - OpenClaw Quant Pipeline
Always-on, event-reactive. Bound to Telegram/WhatsApp channel.

Accepts free-text trading ideas from the operator, parses them into
a valid param_set, and inserts an experiment.started event to kick
off the research pipeline.

Also receives pipeline alerts (workflow.stuck, qa.validated) forwarded
by Hub via sessions_send and relays them to the operator as concise
status messages.
"""

import os
import sys
import json
import uuid
import re
from datetime import datetime, timezone, timedelta
from psycopg2.extras import RealDictCursor

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.sdk import Agent, Event
from hub.router import get_hub

from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
    AGENT_IDEA_INTAKE as AGENT_ID,
    MAX_INTAKE_IN_PROGRESS as MAX_IN_PROGRESS,
    EXP_DUPLICATE_LOOKBACK_DAYS,
    PARAM_LOOKBACK_MIN, PARAM_LOOKBACK_MAX,
    PARAM_ENTRY_MIN, PARAM_ENTRY_MAX,
    PARAM_EXIT_MIN, PARAM_EXIT_MAX,
)


STRATEGY_DEFAULTS = {
    'momentum':       {'lookback_window': 20, 'entry_threshold': 1.5, 'exit_threshold': 0.5},
    'mean_reversion': {'lookback_window': 20, 'entry_threshold': 2.0, 'exit_threshold': 0.5},
    'mean reversion': {'lookback_window': 20, 'entry_threshold': 2.0, 'exit_threshold': 0.5},
    'breakout':       {'lookback_window': 14, 'entry_threshold': 1.0, 'exit_threshold': 0.3},
    'pairs':          {'lookback_window': 30, 'entry_threshold': 2.0, 'exit_threshold': 0.5},
    'trend':          {'lookback_window': 50, 'entry_threshold': 1.5, 'exit_threshold': 0.5},
    'trend following':{'lookback_window': 50, 'entry_threshold': 1.5, 'exit_threshold': 0.5},
}


class IdeaIntakeAgent(Agent):
    """
    Entry point for human trading ideas.
    Parses free text → param_set → experiment.started event.

    Also receives forwarded pipeline events (qa.validated, workflow.stuck)
    from Hub and relays them as operator-friendly messages.
    """

    def __init__(self):
        super().__init__(AGENT_ID, domain='quant')

    def on_event(self, event: Event):
        """
        Handle forwarded pipeline events from the Hub.
        These are events where IdeaIntake is a secondary target
        (e.g. qa.validated, workflow.stuck) — relay to operator.
        """
        if event.event_type == 'qa.validated':
            payload = event.payload or {}
            if payload.get('passed'):
                sid = payload.get('strategy_id', '?')
                ms = payload.get('metrics_summary', {})
                sharpe = ms.get('sharpe_oos', '?')
                dd = ms.get('max_drawdown', '?')
                msg = f"Strategy {sid} promoted. Sharpe OOS: {sharpe}, Drawdown: {dd}"
                self._log(f"NOTIFY OPERATOR: {msg}")
            else:
                sid = payload.get('strategy_id', '?')
                reason = payload.get('rejection_reason', 'see logs')
                self._log(f"NOTIFY OPERATOR: Strategy {sid} rejected: {reason}")

        elif event.event_type == 'workflow.stuck':
            payload = event.payload or {}
            agent = payload.get('agent_name', '?')
            reason = payload.get('reason', 'unknown')
            self._log(f"NOTIFY OPERATOR: Pipeline stuck at {agent}: {reason}")

        elif event.event_type in ('etl.partial', 'etl.failed'):
            payload = event.payload or {}
            failed = payload.get('sources_failed', [])
            self._log(f"NOTIFY OPERATOR: ETL issue — failed sources: {failed}")

        elif event.event_type == 'etl.operator_alert':
            payload = event.payload or {}
            msg = payload.get('message', '')
            self._log(f"NOTIFY OPERATOR: {msg}")

        else:
            self._log(f"Received unexpected event: {event.event_type}")

    def handle_message(self, message: str) -> str:
        message = message.strip()
        self._log(f"Received message: {message[:100]}")

        if self._is_pipeline_alert(message):
            return self._format_pipeline_alert(message)

        if self._is_status_query(message):
            return self._get_pipeline_status()

        return self._process_idea(message)

    def _process_idea(self, text: str) -> str:
        parsed = self._parse_idea(text)
        missing = self._find_missing_fields(parsed)

        if missing:
            return self._ask_clarification(missing, parsed)

        in_progress = self._count_in_progress()
        if in_progress >= MAX_IN_PROGRESS:
            return (f"Pipeline busy: {in_progress} experiments in progress "
                    f"(limit {MAX_IN_PROGRESS}). Try again once some complete.")

        if self._is_duplicate(parsed):
            return ("This param_set was already run in the last 30 days. "
                    "Adjust strategy_type, asset_universe, or date_range to make it distinct.")

        experiment_id = self._insert_experiment(parsed)
        return self._confirm_queued(parsed, experiment_id)

    def _parse_idea(self, text: str) -> dict:
        text_lower = text.lower()
        result = {}

        for stype in STRATEGY_DEFAULTS:
            if stype in text_lower:
                result['strategy_type'] = stype.replace(' ', '_')
                break

        if 'asset_universe' not in result:
            tickers = re.findall(r'\b([A-Z]{2,5}(?:-[A-Z]{2,3})?(?:\.[A-Z]{2})?)\b', text)
            noise = {'I', 'A', 'US', 'UK', 'HK', 'ETF', 'IPO', 'OOS', 'QA'}
            tickers = [t for t in tickers if t not in noise]
            if tickers:
                result['asset_universe'] = tickers

        lw_match = re.search(r'(\d+)\s*(?:day|days|d)\s*lookback', text_lower)
        if lw_match:
            result['lookback_window'] = int(lw_match.group(1))

        entry_match = re.search(r'entry\s*(?:threshold)?\s*[=:@]?\s*([\d.]+)', text_lower)
        if entry_match:
            result['entry_threshold'] = float(entry_match.group(1))

        exit_match = re.search(r'exit\s*(?:threshold)?\s*[=:@]?\s*([\d.]+)', text_lower)
        if exit_match:
            result['exit_threshold'] = float(exit_match.group(1))

        today = datetime.now(timezone.utc).date()
        dr_match = re.search(r'last\s+(\d+)\s+years?', text_lower)
        if dr_match:
            years = int(dr_match.group(1))
            result['date_range'] = {
                'start': str(today.replace(year=today.year - years)),
                'end': str(today - timedelta(days=1))
            }
        elif 'last year' in text_lower or 'recent' in text_lower:
            result['date_range'] = {
                'start': str(today.replace(year=today.year - 1)),
                'end': str(today - timedelta(days=1))
            }
        elif '2022' in text or '2023' in text or '2024' in text:
            years_found = sorted(re.findall(r'\b(20\d\d)\b', text))
            if len(years_found) >= 2:
                result['date_range'] = {
                    'start': f"{years_found[0]}-01-01",
                    'end': f"{years_found[-1]}-12-31"
                }
            elif len(years_found) == 1:
                result['date_range'] = {
                    'start': f"{years_found[0]}-01-01",
                    'end': f"{years_found[0]}-12-31"
                }

        if 'strategy_type' in result:
            defaults = STRATEGY_DEFAULTS.get(result['strategy_type'].replace('_', ' '),
                       STRATEGY_DEFAULTS.get(result['strategy_type'], {}))
            for k, v in defaults.items():
                if k not in result:
                    result[k] = v

        result.setdefault('lookback_window', 20)
        result.setdefault('entry_threshold', 1.5)
        result.setdefault('exit_threshold', 0.5)
        if 'date_range' not in result:
            result['date_range'] = {
                'start': str(today.replace(year=today.year - 3)),
                'end': str(today - timedelta(days=1))
            }

        return result

    def _find_missing_fields(self, parsed: dict) -> list:
        missing = []
        if 'strategy_type' not in parsed:
            missing.append('strategy_type')
        if 'asset_universe' not in parsed:
            missing.append('asset_universe')
        return missing

    def _ask_clarification(self, missing: list, parsed: dict) -> str:
        if 'strategy_type' in missing and 'asset_universe' in missing:
            return ("What strategy type and which assets? "
                    "e.g. 'momentum on AAPL, MSFT, GOOGL' or 'mean reversion on large cap tech'")
        if 'strategy_type' in missing:
            assets = ', '.join(parsed.get('asset_universe', [])[:3])
            return (f"What type of strategy? e.g. momentum, mean_reversion, breakout, pairs "
                    f"(assets detected: {assets})")
        if 'asset_universe' in missing:
            stype = parsed.get('strategy_type', 'strategy')
            return (f"Which assets for the {stype}? "
                    f"e.g. 'AAPL MSFT GOOGL' or 'large cap' or 'crypto'")
        return "Can you clarify the idea a bit more?"

    def _confirm_queued(self, parsed: dict, experiment_id: str) -> str:
        assets = parsed.get('asset_universe', [])
        asset_str = ', '.join(assets[:4])
        if len(assets) > 4:
            asset_str += f' +{len(assets) - 4} more'
        dr = parsed.get('date_range', {})
        return (
            f"Queued: {parsed.get('strategy_type')} on [{asset_str}], "
            f"{dr.get('start')} → {dr.get('end')}.\n"
            f"Lookback: {parsed.get('lookback_window')}d, "
            f"entry: {parsed.get('entry_threshold')}, exit: {parsed.get('exit_threshold')}.\n"
            f"Experiment ID: {experiment_id}"
        )

    def _is_pipeline_alert(self, message: str) -> bool:
        keywords = ['workflow.stuck', 'qa.validated', 'pipeline alert', 'stuck at', 'risk.evaluated']
        return any(k in message.lower() for k in keywords)

    def _format_pipeline_alert(self, message: str) -> str:
        if 'workflow.stuck' in message.lower() or 'stuck at' in message.lower():
            return f"⚠ Pipeline alert: {message}"
        if 'passed=true' in message.lower() or '"passed": true' in message.lower():
            try:
                data = json.loads(message)
                sid = data.get('strategy_id', '?')
                ms = data.get('metrics_summary', {})
                return (f"✓ Strategy {sid} promoted to lineage. "
                        f"Sharpe OOS: {ms.get('sharpe_oos', '?'):.2f}, "
                        f"Drawdown: {ms.get('max_drawdown', '?'):.2f}")
            except Exception:
                return f"✓ Strategy promoted: {message[:120]}"
        if 'passed=false' in message.lower() or '"passed": false' in message.lower():
            try:
                data = json.loads(message)
                sid = data.get('strategy_id', '?')
                reason = data.get('rejection_reason', 'see logs')
                return f"✗ Strategy {sid} rejected: {reason}"
            except Exception:
                return f"✗ Strategy rejected: {message[:120]}"
        return f"Pipeline update: {message[:200]}"

    def _is_status_query(self, message: str) -> bool:
        keywords = ['status', 'what\'s running', "what's running", 'pipeline status',
                    'how many', 'in progress', 'experiments']
        return any(k in message.lower() for k in keywords)

    def _get_pipeline_status(self) -> str:
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM {SCHEMA}.strategy_workflow
                    WHERE status NOT IN ('completed', 'failed')
                """)
                in_progress = cur.fetchone()['cnt']

                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM {SCHEMA}.events
                    WHERE event_type = 'qa.validated'
                    AND created_at >= CURRENT_DATE
                """)
                completed_today = cur.fetchone()['cnt']

                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM {SCHEMA}.events
                    WHERE event_type = 'qa.validated'
                    AND payload_json->>'passed' = 'true'
                    AND created_at >= CURRENT_DATE
                """)
                passed_today = cur.fetchone()['cnt']

                cur.execute(f"""
                    SELECT strategy_id, sharpe_oos FROM {SCHEMA}.strategy_lineage
                    ORDER BY sharpe_oos DESC NULLS LAST LIMIT 1
                """)
                top = cur.fetchone()

            top_str = (f"Best all-time: strategy {top['strategy_id']} "
                       f"(Sharpe OOS {top['sharpe_oos']:.2f})" if top else "No lineage entries yet.")
            return (f"Pipeline status:\n"
                    f"  In progress: {in_progress} experiments\n"
                    f"  Today: {completed_today} evaluated, {passed_today} passed QA\n"
                    f"  {top_str}")
        finally:
            conn.close()

    def _count_in_progress(self) -> int:
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM {SCHEMA}.strategy_workflow
                    WHERE status NOT IN ('completed', 'failed')
                """)
                return cur.fetchone()['cnt']
        finally:
            conn.close()

    def _is_duplicate(self, parsed: dict) -> bool:
        conn = self.hub._get_conn()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(f"""
                    SELECT id, payload_json FROM {SCHEMA}.events
                    WHERE event_type = 'experiment.started'
                    AND domain = 'quant'
                    AND created_at >= NOW() - INTERVAL '30 days'
                    AND payload_json->>'param_set' IS NOT NULL
                """)
                rows = cur.fetchall()
            target = json.dumps(self._build_param_set(parsed), sort_keys=True)
            for row in rows:
                try:
                    existing = json.dumps(
                        json.loads(row['payload_json'] if isinstance(row['payload_json'], str)
                                   else json.dumps(row['payload_json'])).get('param_set', {}),
                        sort_keys=True
                    )
                    if existing == target:
                        return True
                except Exception:
                    continue
            return False
        finally:
            conn.close()

    def _build_param_set(self, parsed: dict) -> dict:
        return {
            'strategy_type':   parsed.get('strategy_type'),
            'lookback_window': parsed.get('lookback_window'),
            'entry_threshold': parsed.get('entry_threshold'),
            'exit_threshold':  parsed.get('exit_threshold'),
            'asset_universe':  sorted(parsed.get('asset_universe', [])),
            'date_range':      parsed.get('date_range'),
        }

    def _create_strategy_workflow(self, strategy_id: str, experiment_id: str, param_set: dict):
        """Create strategy_workflow row before emitting experiment.started."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                asset = param_set.get('asset_universe', [])
                asset_str = asset[0] if asset else 'unknown'
                name = (f"{param_set.get('strategy_type', 'idea')}_{asset_str}_"
                        f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}")
                cur.execute(f"""
                    INSERT INTO {SCHEMA}.strategy_workflow
                        (strategy_id, name, status, experiment_id, assigned_by,
                         created_at, updated_at)
                    VALUES (%s, %s, 'pending', %s, 'qr_idea_intake', now(), now())
                """, (strategy_id, name, experiment_id))
            conn.commit()
            self._log(f"Created strategy_workflow row: {strategy_id}")
        finally:
            conn.close()

    def _insert_experiment(self, parsed: dict) -> str:
        """Insert strategy_workflow + experiment.started event atomically."""
        experiment_id = str(uuid.uuid4())
        strategy_id = str(uuid.uuid4())  # FIX: strategy_id must be set on every event
        param_set = self._build_param_set(parsed)

        # INSERT strategy_workflow FIRST — event must reference an existing strategy
        self._create_strategy_workflow(strategy_id, experiment_id, param_set)

        payload = {
            'experiment_id': experiment_id,
            'strategy_id': strategy_id,
            'param_set': param_set,
            'generation': 1,
            'parent_experiment_id': None,
            'source': 'idea_intake'
        }
        event_id = self.hub.emit_event(
            event_type='experiment.started',
            strategy_id=strategy_id,  # FIX: was None, making event invisible to Hub
            payload=payload,
            source_agent=AGENT_ID,
            domain=DOMAIN
        )
        self._log(f"Inserted experiment.started: experiment_id={experiment_id}, "
                  f"strategy_id={strategy_id}, event_id={event_id}")
        return experiment_id

    def _log(self, message: str):
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{timestamp}] INTAKE: {message}")


def main():
    agent = IdeaIntakeAgent()

    # If called with args or stdin, handle as CLI message (Telegram relay)
    if len(sys.argv) > 1:
        message = ' '.join(sys.argv[1:])
        reply = agent.handle_message(message)
        print(reply)
        return

    # Try reading from stdin (non-blocking for piped input)
    if not sys.stdin.isatty():
        message = sys.stdin.read().strip()
        if message:
            reply = agent.handle_message(message)
            print(reply)
            return

    # No CLI input — run in event-driven mode (process forwarded events from Hub)
    agent.run()


if __name__ == '__main__':
    main()
