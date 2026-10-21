#!/usr/bin/env python3
"""uat_guard_watchdog.py — deadman + Telegram alerter for the UAT registry guard.

Kanban t_9bee1ba6. Runs 23:45 UTC Mon-Fri (after the 22:30 UTC equity topup,
whose step 7 executes audit/uat_registry_guard.py). Reads the guard's latest
verdict file and converts anything non-OK into stdout => the no_agent cron
(deliver=telegram) pushes it.

Alert conditions (exit 1, ALERT lines on stdout):
  ABSENT    verdict file missing, or verdict ts older than the expected window
            (default: today 20:00 UTC) — the guard DID NOT RUN tonight
            (topup died before step 7, host down, cron paused).
  ERROR     guard verdict=ERROR / run_health=DEAD — e.g. mirror stale because
            the UAT session is disconnected (the old data:null crash class,
            now a clean alert instead of a traceback).
  VIOLATION registry/account mismatch — full problem list is echoed.

Exit 0 + empty stdout = silent pass (verdict OK from tonight's run).
"""
import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

DEFAULT_VERDICT = '/home/ubuntu/.hermes/profiles/qr_etl/logs/uat_registry_guard_latest.json'


def main():
    ap = argparse.ArgumentParser(description='UAT guard watchdog / deadman')
    ap.add_argument('--verdict-file', default=DEFAULT_VERDICT)
    ap.add_argument('--expect-since', help='ISO ts; verdict must be newer. '
                    'Default: today 20:00 UTC (post-close guard window).')
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    if args.expect_since:
        expect_since = datetime.fromisoformat(args.expect_since.replace('Z', '+00:00'))
    else:
        expect_since = now.replace(hour=20, minute=0, second=0, microsecond=0)
        if now < expect_since:
            expect_since -= timedelta(days=1)

    alerts = []
    rec = None
    if not os.path.isfile(args.verdict_file):
        alerts.append(f'ABSENT: verdict file {args.verdict_file} does not exist — '
                      'guard never ran')
    else:
        try:
            with open(args.verdict_file) as f:
                rec = json.load(f)
        except Exception as e:
            alerts.append(f'ABSENT: verdict file unreadable ({e}) — guard output corrupt')
    if rec is not None:
        ts = datetime.fromisoformat(str(rec.get('ts')).replace('Z', '+00:00'))
        if ts < expect_since:
            alerts.append(
                f'ABSENT: latest guard verdict ts={ts.isoformat()} < expected '
                f'{expect_since.isoformat()} — tonight\'s post-close guard did not run '
                '(topup failed before step 7, or cron paused)')
        elif rec.get('run_health') == 'DEAD' or rec.get('verdict') == 'ERROR':
            alerts.append(f'ERROR: guard errored at {ts.isoformat()}: '
                          f"{rec.get('error')}")
        elif rec.get('verdict') == 'VIOLATION':
            alerts.append('VIOLATION: registry/account mismatch at '
                          f'{ts.isoformat()}:')
            for p in rec.get('problems', []):
                alerts.append(f'  - {p}')

    if alerts:
        print(f'ALERT uat_guard_watchdog [{now:%Y-%m-%dT%H:%M:%SZ}]')
        for a in alerts:
            print(a)
        if rec is not None:
            print(f'verdict: {json.dumps(rec)}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
