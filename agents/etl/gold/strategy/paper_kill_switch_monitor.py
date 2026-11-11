#!/usr/bin/env python3
"""
paper_kill_switch_monitor.py
============================
Standing rule R3 (book-level honest review 2026-08-05, kanban t_d223563a):

  For every actively-monitored PAPER strategy, if the live paper drawdown
  from peak exceeds 1.5x its audited max_drawdown_oos
  (gold.strategy_registry.max_drawdown_oos), create a RE_AUDIT kanban task
  assigned to qr_research with the strategy_id and live-vs-backtest MDD
  numbers.

Method:
  - Reconstruct the daily paper equity curve from the canonical ledger
    gold.paper_trades_synthetic:
        equity(d) = assigned_capital
                    + sum(realized pnl of trades closed on/before d)
                    + sum(unrealized mtm of positions open on d)
  - MTM uses silver.unified_prices close for that date (last close carried
    forward per ticker; positions entry-priced before first tick).
  - live_dd = (peak_equity - latest_equity) / peak_equity
  - breach  = live_dd > KILL_SWITCH_MULT * max_drawdown_oos

On breach:
  - `hermes kanban create` a RE_AUDIT task on the trading board, assignee
    qr_research, idempotency-key kill-switch-reaudit-<strategy_id> so a
    non-archived existing task dedups repeat alerts.
  - Append a row to gold.paper_kill_switch_log (audit trail, all strategies
    checked, breach or not).

Cadence: daily, after "Refresh synthetic paper trades" (pipeline_manifest
gold stage). Run with the ETL venv python.
"""
import json
import os
import subprocess
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
ETL_SHARED = os.path.normpath(os.path.join(HERE, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, ETL_SHARED)

from db import get_connection  # noqa: E402

KILL_SWITCH_MULT = 1.5
HERMES_BIN = '/home/ubuntu/.local/bin/hermes'
KANBAN_BOARD = 'trading'
REAUDIT_ASSIGNEE = 'qr_research'

DDL = """
CREATE TABLE IF NOT EXISTS gold.paper_kill_switch_log (
    id            bigserial PRIMARY KEY,
    as_of_date    date NOT NULL,
    strategy_id   text NOT NULL,
    assigned_capital numeric,
    equity        numeric,
    peak_equity   numeric,
    live_dd_pct   numeric,
    mdd_oos       numeric,
    threshold_pct numeric,
    breached      boolean NOT NULL,
    kanban_task_id text,
    note          text,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS paper_kill_switch_log_day_strategy
    ON gold.paper_kill_switch_log (as_of_date, strategy_id);
"""

SQL_STRATEGIES = """
SELECT r.strategy_id, r.assigned_capital, r.max_drawdown_oos
FROM gold.strategy_registry r
JOIN gold.strategy_paper_monitoring m
  ON m.strategy_id = r.strategy_id AND m.is_active = true
WHERE r.execution_mode = 'PAPER'
  AND r.max_drawdown_oos IS NOT NULL
  AND (
    (r.status = 'paper' AND r.retired_at IS NULL)
    OR
    -- MANAGED RUNOFF (t_0daa8eaf): a retired book with open paper legs
    -- keeps kill-switch/MDD coverage until the runoff completes (the
    -- rebalancer's flat sweep deactivates monitoring once fully flat).
    (r.retired_at IS NOT NULL
     AND EXISTS (SELECT 1 FROM gold.paper_trades_synthetic p
                 WHERE p.strategy_id = r.strategy_id AND p.status = 'open'))
  )
ORDER BY r.strategy_id;
"""

SQL_TRADES = """
SELECT ticker, entry_date, entry_price, n_shares, exit_date, pnl
FROM gold.paper_trades_synthetic
WHERE strategy_id = %s
ORDER BY entry_date;
"""

SQL_PRICES = """
SELECT date, ticker, close
FROM silver.unified_prices
WHERE ticker = ANY(%s) AND date >= %s AND close IS NOT NULL
ORDER BY date, ticker;
"""

SQL_LOG = """
INSERT INTO gold.paper_kill_switch_log
  (as_of_date, strategy_id, assigned_capital, equity, peak_equity,
   live_dd_pct, mdd_oos, threshold_pct, breached, kanban_task_id, note)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
ON CONFLICT (as_of_date, strategy_id) DO UPDATE SET
  assigned_capital = EXCLUDED.assigned_capital,
  equity           = EXCLUDED.equity,
  peak_equity      = EXCLUDED.peak_equity,
  live_dd_pct      = EXCLUDED.live_dd_pct,
  mdd_oos          = EXCLUDED.mdd_oos,
  threshold_pct    = EXCLUDED.threshold_pct,
  breached         = EXCLUDED.breached,
  kanban_task_id   = COALESCE(EXCLUDED.kanban_task_id,
                              gold.paper_kill_switch_log.kanban_task_id),
  note             = EXCLUDED.note;
"""


def build_equity_curve(trades, prices_by_date, all_dates, capital):
    """Return (equity_series, peak, last). trades: list of dicts with
    entry_date/exit_date/entry_price/n_shares/pnl. prices_by_date:
    {date: {ticker: close}}. all_dates: sorted trading dates."""
    realized_by_date = {}
    for t in trades:
        if t['exit_date'] is not None and t['pnl'] is not None:
            realized_by_date[t['exit_date']] = (
                realized_by_date.get(t['exit_date'], 0.0) + float(t['pnl']))

    last_px = {}
    equity = []
    realized_cum = 0.0
    for d in all_dates:
        realized_cum += realized_by_date.get(d, 0.0)
        if d in prices_by_date:
            last_px.update({k: float(v) for k, v in prices_by_date[d].items()})
        unreal = 0.0
        for t in trades:
            open_on_d = t['entry_date'] <= d and (
                t['exit_date'] is None or t['exit_date'] > d)
            if not open_on_d:
                continue
            px = last_px.get(t['ticker'])
            if px is None:
                px = float(t['entry_price'])  # no tick yet -> entry
            unreal += (px - float(t['entry_price'])) * float(t['n_shares'])
        equity.append(capital + realized_cum + unreal)
    if not equity:
        return None, None, None
    peak = max(equity)
    return equity, peak, equity[-1]


def create_reaudit_task(sid, live_dd, mdd_oos, peak, equity):
    title = (f"RE_AUDIT: {sid} — live paper DD {live_dd*100:.2f}% exceeds "
             f"1.5x audited MDD {mdd_oos*100:.2f}% (R3 kill-switch)")
    body = (
        f"Standing rule R3 kill-switch fired (paper_kill_switch_monitor.py, "
        f"daily gold stage).\n\n"
        f"- strategy_id: {sid}\n"
        f"- live paper drawdown from peak: {live_dd*100:.2f}%\n"
        f"- audited max_drawdown_oos: {mdd_oos*100:.2f}%\n"
        f"- kill-switch threshold (1.5x): {1.5*mdd_oos*100:.2f}%\n"
        f"- peak paper equity: {peak:.2f}\n"
        f"- current paper equity: {equity:.2f}\n\n"
        f"Action: re-audit the strategy's OOS metrics against live paper "
        f"behaviour; decide retire / recalibrate / keep with tighter limit.\n"
        f"Context: book-level honest review 2026-08-05 (t_d223563a)."
    )
    cmd = [
        HERMES_BIN, 'kanban', 'create', '--board', KANBAN_BOARD,
        '--assignee', REAUDIT_ASSIGNEE,
        '--idempotency-key', f'kill-switch-reaudit-{sid}',
        '--body', body, '--json', title,
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if out.returncode != 0:
            return None, f"kanban create rc={out.returncode}: {out.stderr.strip()[:300]}"
        try:
            return json.loads(out.stdout).get('id'), None
        except Exception:
            return None, f"kanban create unparsable stdout: {out.stdout[:200]}"
    except Exception as e:
        return None, f"kanban create failed: {e}"


def main():
    today = date.today()
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(DDL)

    cur.execute(SQL_STRATEGIES)
    strategies = cur.fetchall()
    print(f"kill-switch check: {len(strategies)} monitored PAPER strategies, "
          f"mult={KILL_SWITCH_MULT}x, as_of={today}")

    n_breach = 0
    for sid, capital, mdd_oos in strategies:
        capital = float(capital or 0)
        mdd_oos = float(mdd_oos)
        cur.execute(SQL_TRADES, (sid,))
        cols = [d[0] for d in cur.description]
        trades = [dict(zip(cols, r)) for r in cur.fetchall()]
        note = None
        task_id = None
        breached = False
        live_dd = None
        peak = equity = None

        if not trades or capital <= 0:
            # No ledger exposure -> equity == capital, DD = 0 by definition.
            equity = peak = capital
            live_dd = 0.0
            note = 'no paper trades or zero capital — flat book, DD=0'
        else:
            tickers = sorted({t['ticker'] for t in trades})
            first_date = min(t['entry_date'] for t in trades)
            cur.execute(SQL_PRICES, (tickers, first_date))
            prices_by_date = {}
            all_dates = set()
            for d, tk, cl in cur.fetchall():
                prices_by_date.setdefault(d, {})[tk] = cl
                all_dates.add(d)
            all_dates = sorted(all_dates)
            if not all_dates:
                # No price coverage for held tickers (e.g. flat CASH book
                # onboarded today) — value at entry, DD = 0, flag in note.
                all_dates = [today]
                note = 'no price coverage — valued at entry, DD=0'
            series, peak, equity = build_equity_curve(
                trades, prices_by_date, all_dates, capital)
            if series is None or not peak:
                live_dd = None
                note = (note or '') + ' equity curve empty — skipped'
            else:
                live_dd = (peak - equity) / peak
                breached = live_dd > KILL_SWITCH_MULT * mdd_oos

        if breached:
            n_breach += 1
            task_id, err = create_reaudit_task(sid, live_dd, mdd_oos, peak, equity)
            note = err or f"RE_AUDIT task {task_id} created/deduped"
            print(f"  BREACH {sid}: live_dd={live_dd*100:.2f}% "
                  f"thr={KILL_SWITCH_MULT*mdd_oos*100:.2f}% task={task_id} {err or ''}")
        else:
            dd_txt = 'n/a' if live_dd is None else f"{live_dd*100:.2f}%"
            print(f"  ok     {sid}: live_dd={dd_txt} "
                  f"thr={KILL_SWITCH_MULT*mdd_oos*100:.2f}% {note or ''}")

        cur.execute(SQL_LOG, (
            today, sid, capital, equity, peak,
            None if live_dd is None else round(live_dd, 6),
            mdd_oos, round(KILL_SWITCH_MULT * mdd_oos, 6),
            breached, task_id, note))

    conn.commit()
    cur.close()
    conn.close()
    print(f"kill-switch done: {n_breach} breach(es) of {len(strategies)}")
    # Breaches are surfaced via kanban tasks; exit 0 so the daily pipeline
    # does not red-flag on a correctly-detected breach.


if __name__ == '__main__':
    main()
