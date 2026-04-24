#!/usr/bin/env python3
"""
ETL Manager Agent — OpenClaw Quant Pipeline
Isolated agent: owns the full data supply chain.

Responsibilities:
  - Run daily_refresh.sh on schedule (bronze → silver → gold → consumption)
  - Manage API credentials for FMP, Binance, Coinbase, IBKR
  - Handle manual data loads from operator via Telegram
  - Emit etl.completed / etl.partial / etl.failed events
  - Write gold_layer_state before/during/after refresh (lock mechanism)
  - Report pipeline status on operator request

Lifecycle: Always-on (isolated). Woken by HEARTBEAT or operator message.
Does NOT exit between refreshes — persists to handle ad-hoc operator requests.
"""

import os
import sys
import json
import subprocess
from datetime import datetime, timezone, date

sys.path.insert(0, '/home/ubuntu/.openclaw/workspace/quant_research')
from hub.sdk import Agent, Event

from agents.shared.constants import (
    SCHEMA, QUANT_DOMAIN as DOMAIN,
)

AGENT_ID     = 'qr_etl_manager'
ETL_BASE     = os.path.join(os.path.dirname(__file__), '..', 'etl')
REFRESH_SCRIPT = os.path.join(ETL_BASE, 'daily_refresh.sh')

# Bronze sources in dependency order
BRONZE_SOURCES = [
    ('yfinance',  'bronze/yfinance/ingest_yfinance.py',   None),
    ('fmp',       'bronze/fmp/ingest_fmp.py',             'FMP_API_KEY'),
    ('binance',   'bronze/binance/ingest_binance.py',     'BINANCE_API_KEY'),
    ('coinbase',  'bronze/coinbase/ingest_coinbase.py',   'COINBASE_API_KEY'),
    ('ibkr',      'bronze/ibkr/ingest_ibkr.py',          'IBKR_HOST'),
    ('hkex',      'bronze/hkex/ingest_hkex.py',          None),
    ('manual',    'bronze/manual/ingest_manual.py',       None),
]


class ETLManagerAgent(Agent):
    """
    ETL Manager — data supply chain owner.
    Consumes: HEARTBEAT (daily cron), operator messages, etl.refresh_requested
    Emits:    etl.completed, etl.partial, etl.failed
    """

    def __init__(self):
        super().__init__(AGENT_ID, domain=DOMAIN)
        self.last_refresh: dict | None = None

    # ─── Gold layer state management ─────────────────────────────────────────

    def _set_gold_layer_state(self, state: str, notes: str = '',
                               sources_ok=None, sources_failed=None,
                               lock: bool = False):
        """
        Write gold_layer_state table.
        state: 'ready' | 'stale' | 'locked' | 'partial'
        Called by ETL Manager at start (locked), end (ready/partial/stale), and on failure.
        """
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.gold_layer_state SET
                        state          = %s,
                        notes          = %s,
                        sources_ok     = %s,
                        sources_failed = %s,
                        locked_since   = CASE WHEN %s THEN NOW() ELSE NULL END,
                        refreshed_at   = CASE WHEN %s IN ('ready','partial') THEN NOW() ELSE refreshed_at END,
                        updated_at     = NOW()
                """, (
                    state, notes,
                    json.dumps(sources_ok or []),
                    json.dumps(sources_failed or []),
                    lock, state
                ))
            conn.commit()
            self._log(f"Gold layer state → {state}. {notes}")
        except Exception as e:
            self._log(f"WARNING: could not update gold_layer_state: {e}")
        finally:
            conn.close()

    def _is_refresh_already_running(self) -> bool:
        """Idempotency guard: returns True if gold_layer_state is currently 'locked'."""
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT state, locked_since
                    FROM {SCHEMA}.gold_layer_state LIMIT 1
                """)
                row = cur.fetchone()
                if row and row[0] == 'locked':
                    self._log(f"Refresh already locked since {row[1]} — skipping duplicate run.")
                    return True
                return False
        except Exception:
            return False
        finally:
            conn.close()

    # ─── Event dispatch ───────────────────────────────────────────────────────

    def on_event(self, event: Event):
        if event.event_type == 'HEARTBEAT':
            self._run_daily_refresh()
        elif event.event_type == 'etl.refresh_requested':
            self._run_daily_refresh(manual=True)
        elif event.event_type == 'operator.message':
            self._handle_operator_message(event.payload.get('text', ''))
        else:
            self._log(f"Unhandled event: {event.event_type}")

    # ─── Daily refresh ────────────────────────────────────────────────────────

    def _run_daily_refresh(self, manual: bool = False):
        trigger = "manual request" if manual else "scheduled heartbeat"
        self._log(f"Starting daily refresh ({trigger})")

        # Idempotency: bail if already running
        if self._is_refresh_already_running():
            self._alert_operator(
                "Refresh already in progress (gold_layer_state = locked). "
                "Will not start a duplicate run."
            )
            return

        # Acquire lock — tells Data Validator to block experiments
        self._set_gold_layer_state(
            state='locked',
            notes=f'ETL refresh started ({trigger})',
            lock=True
        )

        sources_ok     = []
        sources_failed = []

        # Run each bronze source individually for granular failure handling
        for name, script_rel, cred_var in BRONZE_SOURCES:
            script = os.path.join(ETL_BASE, script_rel)
            if not os.path.exists(script):
                self._log(f"  [{name}] script not found — skipping")
                continue

            # Check required credential
            if cred_var and not os.environ.get(cred_var):
                msg = f"{name} ingestion skipped — {cred_var} not set. Please send the key via Telegram."
                self._log(f"  [{name}] SKIP: {msg}")
                sources_failed.append({'source': name, 'reason': f'missing {cred_var}'})
                self._alert_operator(msg)
                continue

            # Refinement 3: skip sources already ingested today (idempotent)
            if self._source_already_ingested_today(name):
                sources_ok.append(name)
                continue

            ok, err = self._run_script(script)
            if ok:
                self._log(f"  [{name}] OK")
                sources_ok.append(name)
                self._mark_source_ok_in_state(name)  # persist for resume
            else:
                self._log(f"  [{name}] FAILED: {err}")
                sources_failed.append({'source': name, 'reason': err[:200]})
                self._alert_operator(
                    f"{name} ingestion failed: {err[:200]}\n"
                    f"Remaining sources will continue."
                )

        # Silver → Gold → Consumption via daily_refresh.sh (skips bronze — already ran)
        self._log("Running silver/gold/consumption layers...")
        ok, err = self._run_script(REFRESH_SCRIPT, env_extra={'SKIP_BRONZE': '1'})
        if not ok:
            self._log(f"Silver/gold/consumption failed: {err}")

        # Record and emit
        self.last_refresh = {
            'timestamp':      datetime.now(timezone.utc).isoformat(),
            'sources_ok':     sources_ok,
            'sources_failed': sources_failed,
        }

        if not sources_failed:
            event_type  = 'etl.completed'
            gold_state  = 'ready'
            gold_notes  = f'Full refresh complete. All {len(sources_ok)} sources OK.'
        elif sources_ok:
            event_type  = 'etl.partial'
            gold_state  = 'partial'
            failed_names = ', '.join(f['source'] for f in sources_failed)
            gold_notes  = f'Partial refresh. Failed sources: {failed_names}. Data may have gaps.'
        else:
            event_type  = 'etl.failed'
            gold_state  = 'stale'
            gold_notes  = 'Full refresh failed. Gold layer not updated.'

        # Release lock and record final state
        self._set_gold_layer_state(
            state=gold_state,
            notes=gold_notes,
            sources_ok=sources_ok,
            sources_failed=sources_failed,
            lock=False
        )

        self.emit_event(
            event_type=event_type,
            payload={
                'refresh_date':    date.today().isoformat(),
                'sources_ok':      sources_ok,
                'sources_failed':  sources_failed,
                'gold_layer_state': gold_state,
            }
        )
        self._log(f"Refresh complete → {event_type} (gold layer: {gold_state})")

    # ─── Operator message handling ────────────────────────────────────────────

    def _handle_operator_message(self, text: str):
        """Route operator messages: status queries, credentials, manual loads."""
        text_lower = text.strip().lower()

        if text_lower in ('status', 'etl status', 'refresh status'):
            self._report_status()

        elif text_lower in ('refresh', 'run refresh', 'force refresh'):
            self._run_daily_refresh(manual=True)

        elif '=' in text and any(k in text.upper() for k in [
            'API_KEY', 'SECRET', 'IBKR_HOST', 'FMP_', 'BINANCE_', 'COINBASE_'
        ]):
            self._receive_credential(text.strip())

        elif text_lower.endswith('.csv') or 'manual' in text_lower:
            self._log(f"Operator mentions manual load: {text}")
            self._alert_operator(
                "To load manual data, send the CSV file path on the EC2 instance "
                "or paste the CSV content directly. I will confirm row count and "
                "tickers before writing."
            )

        else:
            self._alert_operator(
                "ETL Manager commands:\n"
                "  status            — last refresh summary\n"
                "  refresh           — trigger full refresh now\n"
                "  KEY=value         — set an API credential\n"
                "  (send a .csv)     — manual data load"
            )

    def _receive_credential(self, text: str):
        """Parse and set a KEY=value credential from the operator."""
        try:
            key, value = text.split('=', 1)
            key   = key.strip()
            value = value.strip()
            os.environ[key] = value
            self._log(f"Credential received: {key} (value not logged)")
            self._alert_operator(
                f"Received {key}. Retrying affected source now..."
            )
            # Find which source uses this key and retry it
            for name, script_rel, cred_var in BRONZE_SOURCES:
                if cred_var == key:
                    # Refinement 3: if already ingested today, don't duplicate
                    if self._source_already_ingested_today(name):
                        self._alert_operator(
                            f"{name} already succeeded today — no retry needed. "
                            f"New key saved for tomorrow's refresh."
                        )
                        return
                    script = os.path.join(ETL_BASE, script_rel)
                    ok, err = self._run_script(script)
                    if ok:
                        self._mark_source_ok_in_state(name)
                        self._alert_operator(f"{name} ingestion succeeded with new key.")
                    else:
                        self._alert_operator(f"{name} still failing: {err[:200]}")
                    return
            self._alert_operator(f"{key} set. It will be used on the next refresh.")
        except ValueError:
            self._alert_operator(
                "Could not parse credential. Send as KEY=value on a single line."
            )

    def _report_status(self):
        if not self.last_refresh:
            self._alert_operator("No refresh has run yet this session.")
            return

        r = self.last_refresh
        ok_list   = ', '.join(r['sources_ok']) or 'none'
        fail_list = ', '.join(f['source'] for f in r['sources_failed']) or 'none'
        msg = (
            f"ETL status as of {r['timestamp']} UTC\n"
            f"  Sources OK:     {ok_list}\n"
            f"  Sources failed: {fail_list}\n"
        )
        if r['sources_failed']:
            for f in r['sources_failed']:
                msg += f"  ✗ {f['source']}: {f['reason']}\n"
        self._alert_operator(msg)

    # ─── Idempotency helpers ─────────────────────────────────────────────────

    def _source_already_ingested_today(self, source_name: str) -> bool:
        """
        Refinement 3: check if this bronze source already succeeded today.
        Prevents duplicate writes when operator takes hours to supply a credential
        and a new retry is triggered — sources that already ran are skipped.
        """
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT 1 FROM {SCHEMA}.gold_layer_state
                    WHERE sources_ok ? %s
                      AND DATE(refreshed_at) = CURRENT_DATE
                    LIMIT 1
                """, (source_name,))
                already_done = cur.fetchone() is not None
                if already_done:
                    self._log(f"  [{source_name}] already succeeded today — skipping (idempotent)")
                return already_done
        except Exception:
            return False  # if unsure, allow the run
        finally:
            conn.close()

    def _mark_source_ok_in_state(self, source_name: str):
        """
        Append a successful source to sources_ok in gold_layer_state.
        Allows partial resume: if ETL was interrupted mid-run,
        sources already ingested won't re-run on the next attempt.
        """
        conn = self.hub._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f"""
                    UPDATE {SCHEMA}.gold_layer_state
                    SET sources_ok = COALESCE(sources_ok, '[]'::jsonb) || %s::jsonb,
                        updated_at = NOW()
                """, (json.dumps([source_name]),))
            conn.commit()
        except Exception as e:
            self._log(f"WARNING: could not mark {source_name} ok in state: {e}")
        finally:
            conn.close()

    # ─── Helpers ─────────────────────────────────────────────────────────────

    def _run_script(self, script_path: str, env_extra: dict = None):
        """Run a Python or shell script. Returns (success, stderr_snippet)."""
        env = {**os.environ, **(env_extra or {})}
        try:
            if script_path.endswith('.sh'):
                cmd = ['bash', script_path]
            else:
                cmd = ['python3', script_path]
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=1800, env=env,
                cwd=ETL_BASE
            )
            if result.returncode == 0:
                return True, ''
            return False, (result.stderr or result.stdout)[-500:]
        except subprocess.TimeoutExpired:
            return False, 'timeout after 30 min'
        except Exception as e:
            return False, str(e)

    def _alert_operator(self, message: str):
        """Forward a message to Idea Intake → operator via sessions_send."""
        try:
            self.emit_event(
                event_type='etl.operator_alert',
                payload={'message': message, 'source_agent': AGENT_ID},
            )
        except Exception as e:
            self._log(f"Could not alert operator: {e}")

    def _log(self, message: str):
        ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
        print(f"[{ts}] ETL MANAGER: {message}", flush=True)


def main():
    agent = ETLManagerAgent()
    agent.run()


if __name__ == '__main__':
    main()
