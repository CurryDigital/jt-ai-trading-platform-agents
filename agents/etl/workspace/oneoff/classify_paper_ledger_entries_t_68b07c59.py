#!/usr/bin/env python3
"""Classify paper ledger entries: rebalance / drift / spurious re-entry.

Kanban t_68b07c59 (findings memo 2026-08-17, section 2.1). The paper engine
historically rebalanced on EVERY daily signal cycle regardless of declared
cadence, so monthly/weekly strategies accumulated mid-period position entries
on daily rank flips. This script classifies every ENTRY event in
gold.paper_trades_synthetic for weekly/monthly strategies:

  rebalance        - part of the strategy's first entry wave within its
                     cadence period (calendar month / ISO week): entry_date
                     equals the strategy's earliest entry_date in that period,
                     and the ticker was not recently closed.
  spurious re-entry - the same (strategy, ticker) has a closed row with
                     exit_date within 7 calendar days before this entry
                     (close -> reopen churn on daily rank flips).
  drift            - mid-period entry of a ticker with no recent close
                     (portfolio drifting away from the last rebalance target
                     as daily signals flip).

Read-only. Prints a per-strategy report and a full row listing.

Run:  python classify_paper_ledger_entries_t_68b07c59.py
"""
import os
import sys
from datetime import date, timedelta

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path:
    sys.path.insert(0, _ETL_SHARED)

from db import get_connection  # noqa: E402

REENTRY_WINDOW_DAYS = 7

SQL_ROWS = """
SELECT p.strategy_id, r.frequency, p.ticker, p.entry_date, p.exit_date,
       p.status, p.entry_price, p.exit_price, p.pnl
FROM gold.paper_trades_synthetic p
JOIN gold.strategy_registry r USING (strategy_id)
WHERE lower(COALESCE(r.frequency, '')) IN ('weekly', 'monthly')
ORDER BY p.strategy_id, p.ticker, p.entry_date;
"""


def period_key(freq, d):
    if freq == 'weekly':
        iso = d.isocalendar()
        return f"W:{iso[0]}-{iso[1]:02d}"
    return f"M:{d.year}-{d.month:02d}"


def main():
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(SQL_ROWS)
        rows = cur.fetchall()
        cur.close()
    finally:
        conn.close()

    # Group entries per strategy; collect closed rows per (strategy, ticker).
    by_strategy = {}
    closed_by_pair = {}
    for (sid, freq, ticker, entry, exit_, status, eprice, xprice, pnl) in rows:
        freq = (freq or '').lower()
        by_strategy.setdefault(sid, {'freq': freq, 'entries': []})
        by_strategy[sid]['entries'].append({
            'ticker': ticker, 'entry': entry, 'exit': exit_, 'status': status,
            'entry_price': eprice, 'pnl': pnl,
        })
        if status == 'closed' and exit_ is not None:
            closed_by_pair.setdefault((sid, ticker), []).append(exit_)

    report_lines = []
    detail_lines = []
    totals = {'rebalance': 0, 'drift': 0, 'spurious re-entry': 0}

    for sid in sorted(by_strategy):
        freq = by_strategy[sid]['freq']
        entries = by_strategy[sid]['entries']
        # First entry wave per period: min entry_date within (strategy, period).
        first_wave = {}
        for e in entries:
            pk = period_key(freq, e['entry'])
            first_wave[pk] = min(first_wave.get(pk, e['entry']), e['entry'])

        counts = {'rebalance': 0, 'drift': 0, 'spurious re-entry': 0}
        for e in entries:
            pk = period_key(freq, e['entry'])
            recent_closes = [x for x in closed_by_pair.get((sid, e['ticker']), [])
                             if e['entry'] - timedelta(days=REENTRY_WINDOW_DAYS) <= x < e['entry']]
            if recent_closes:
                cls = 'spurious re-entry'
            elif e['entry'] == first_wave[pk]:
                cls = 'rebalance'
            else:
                cls = 'drift'
            counts[cls] += 1
            totals[cls] += 1
            detail_lines.append(
                f"  {sid}  {e['ticker']:<10} entry={e['entry']}  "
                f"exit={str(e['exit'] or '-'):<10}  {e['status']:<6}  -> {cls}"
            )
        report_lines.append(
            f"{sid:<45} {freq:<8} entries={len(entries):<4} "
            f"rebalance={counts['rebalance']:<4} drift={counts['drift']:<4} "
            f"spurious_reentry={counts['spurious re-entry']:<4} "
            f"contaminated={counts['drift'] + counts['spurious re-entry']}"
        )

    print("=" * 100)
    print("PAPER LEDGER ENTRY CLASSIFICATION (weekly/monthly strategies) — t_68b07c59")
    print(f"re-entry window: {REENTRY_WINDOW_DAYS}d; periods: calendar month / ISO week")
    print("=" * 100)
    for line in report_lines:
        print(line)
    print("-" * 100)
    total_entries = sum(totals.values())
    print(f"TOTAL entries={total_entries}  rebalance={totals['rebalance']}  "
          f"drift={totals['drift']}  spurious_reentry={totals['spurious re-entry']}  "
          f"contaminated={totals['drift'] + totals['spurious re-entry']} "
          f"({(totals['drift'] + totals['spurious re-entry']) / total_entries * 100:.1f}% of entries)"
          if total_entries else "TOTAL: no entries")
    print()
    print("DETAIL (non-rebalance entries only):")
    for line in detail_lines:
        if '-> rebalance' not in line:
            print(line)


if __name__ == '__main__':
    main()
