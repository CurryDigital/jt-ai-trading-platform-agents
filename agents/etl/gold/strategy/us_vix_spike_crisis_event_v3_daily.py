#!/usr/bin/env python3
"""
Daily signal generator: us_vix_spike_crisis_event_v3 (kanban t_de0986e1)
==========================================================================
US VIX-Spike Crisis Event GLD/SPY 50/50 — event-driven crisis sleeve,
mostly CASH. Approved 2026-09-23 (4-stage audit PASS x4 incl
qa_reproduction + independent honesty subagent PASS with EXPERIMENTAL-only
restriction; engine of record:
qr_research/workspace/vix_spike_event_batch/engine.py).

Rule fidelity to the research engine (engine.py, run_variant V3):
  - Events: gold.vix_regime.vix_z60 crosses from <2 to >=2 with episode
    dedup: once an event fires, the trigger is disarmed until z < 1
    (TRIG=2.0, REARM=1.0, scanned over FULL z history 2019-01 onward —
    episode state carries across window boundaries exactly like the engine).
  - Calendar: GLD trading days from silver.unified_prices
    (close NOT NULL, > 0). Events on non-GLD-trading days never fill
    (engine iterates the GLD bar calendar only).
  - Entry: event day d sets a pending fill; the position opens at the close
    of the NEXT GLD bar (next-trading-day close).
  - Exit: pure time exit — close at entry_bar + 20 trading days.
  - First event wins: a new event can only arm when the book is flat and
    nothing is pending; overlapping events are permanently ignored.
  - No future data: event detection uses event-day z only.

Book semantics (FLAT at go-live — different from retired drift V3):
  qr_research seeded the book 2026-09-23 FLAT (CASH 100 HOLD + GLD/SPY
  0 HOLD; last trade exited 2026-08-27). This script runs a CONTINUOUS
  full-history replay (z from 2019-01-02, the engine's data start) so the
  computed book is by construction the research book at every date. Hard
  seed assertions pin the replay BEFORE any DB write:
    1. Replayed OOS trades (entry in [2025-01-01, SEED_CHECK_DATE]) must
       equal the 6 events in gold.strategy_backtest_trades on exact
       (entry_date, exit_date) — the audited engine output.
    2. Book at SEED_CHECK_DATE (2026-09-22, latest data at go-live) must
       be FLAT with no pending entry (matches the seeded signal file).
  Any drift fails the run loudly before any DB write.

Signal emitted (target portfolio, weights_are_target_portfolio=True):
  - Position open OR entry pending (event fired on as_of, fills next bar):
    GLD 50 BUY + SPY 50 BUY + CASH 0 HOLD.
  - Otherwise: CASH 100 HOLD + GLD 0 HOLD + SPY 0 HOLD (the seeded flat
    shape; verify_post_handoff_db.py flags the CASH row as stray — that is
    the DESIGNED flat state, do not clean up).

Run cadence: daily via run_signal_cycle.sh (step 1e), after
build_rotation_signals.py (which skips this strategy — no engine config —
so these rows are the final writer) and before snapshot + rebalancer.
Registry frequency='daily' so the rebalancer acts every cycle.

Writes (idempotent; delete-then-insert per strategy):
  - gold.strategy_ticker_scores : 3 rows (GLD, SPY, CASH).
  - consumption.signal_logs     : one row per score row (signal=1).
  - gold.strategy_registry      : last_signal_at, signal_file_path -> audit JSON.
  - Audit JSON: agents/etl/data/signals/us_vix_spike_crisis_event_v3/
    us_vix_spike_crisis_event_v3_signals_YYYY-MM-DD.json

Book rules (observer-only HOLD per user 2026-09-23 — c1 paper-flat observer
pattern):
  Registration PAUSED, not rejected. assigned_capital=$0.00: the rebalancer
  enrolls the strategy but sizes every position to 0, so NO paper capital is
  deployed (hk_ipo_postlisting_drift_c1 precedent: 0 paper trades). Signal
  flow (this script: daily vix_z60 event detection + ticker_scores) is wired
  for VALIDATION ONLY while two research questions stay open (Feb-2026
  GLD-leg conditioning variable; unbiased re-run without first-wins skip).
  No stage transition without explicit user call. Kill-switch monitor stays
  enrolled via the active gold.strategy_paper_monitoring row (threshold
  1.5x audited -11.63% = -17.4%); 6-month evidence clock is research-side.
  execution_mode=PAPER (NOT PAPER_UAT — t_fbbde37e).
"""
import json
import os
import sys
from datetime import date, datetime, timezone

ETL_HOME = os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl")
sys.path.insert(0, os.path.join(ETL_HOME, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

from db import get_connection  # noqa: E402

SID = "us_vix_spike_crisis_event_v3"
GO_LIVE = date(2026, 9, 23)           # first live signal date
SEED_CHECK_DATE = date(2026, 9, 22)   # latest data at go-live (book FLAT)
OOS_START = date(2025, 1, 1)          # engine OOS window start
TRIG, REARM = 2.0, 1.0                # engine TRIG / REARM
HOLD_TD = 20                          # engine HOLD_TD
LEGS = {"GLD": 0.5, "SPY": 0.5}       # engine V3 legs
AUDIT_DIR = os.path.join(ETL_HOME, "data", "signals", SID)

Z_SQL = ("SELECT date, vix_z60 FROM gold.vix_regime "
         "WHERE vix_z60 IS NOT NULL ORDER BY date")
CAL_SQL = ("SELECT date FROM silver.unified_prices "
           "WHERE ticker = 'GLD' AND close IS NOT NULL AND close > 0 "
           "ORDER BY date")
SEED_TRADES_SQL = ("""
    SELECT DISTINCT entry_date, exit_date
    FROM gold.strategy_backtest_trades
    WHERE strategy_id = %s ORDER BY entry_date
""")


def events_from(z):
    """engine.py events_from: episode-dedup cross >= TRIG, re-arm < REARM,
    scanned over the full z history (state carries across windows)."""
    ev, in_ep = set(), False
    for d, v in z:
        if not in_ep and v >= TRIG:
            ev.add(d)
            in_ep = True
        elif in_ep and v < REARM:
            in_ep = False
    return ev


def replay(cal, evset):
    """engine.py run_variant control flow (V3: no early exit), state only.
    Iteration order per bar, exactly as the engine:
      1. fill pending entry at THIS close (if flat)
      2. time-exit check (held >= HOLD_TD bars)
      3. arm a new event (only if flat and nothing pending)
    Returns (trades, open_pos, pending) where
    trades = [(trigger_d, entry_d, exit_d)],
    open_pos = (trigger_d, entry_d, entry_i) or None,
    pending = event date or None."""
    trades = []
    open_pos = None     # (trigger_date, entry_date, entry_index)
    pending = None
    for i, d in enumerate(cal):
        if pending is not None and open_pos is None:
            open_pos = (pending, d, i)  # fill at this bar's close
            pending = None
        if open_pos is not None:
            if i - open_pos[2] >= HOLD_TD:
                trades.append((open_pos[0], open_pos[1], d))
                open_pos = None
        if d in evset and open_pos is None and pending is None:
            pending = d
    return trades, open_pos, pending


def assert_seed_state(cur, cal, evset):
    """Pin the continuous replay to the seeded/audited book. Loud failure —
    any divergence means live data restated away from the approved research
    book; investigate before writing signals."""
    # 1. OOS trades must equal the audited backtest events exactly.
    cal_seed = [d for d in cal if d <= SEED_CHECK_DATE]
    trades, open_seed, pending_seed = replay(cal_seed, evset)
    replay_oos = sorted(
        (e, x) for _, e, x in trades if OOS_START <= e <= SEED_CHECK_DATE)
    cur.execute(SEED_TRADES_SQL, (SID,))
    db_oos = sorted((e, x) for e, x in cur.fetchall())
    if replay_oos != db_oos:
        raise RuntimeError(
            f"SEED ASSERTION FAILED: replayed OOS trades {replay_oos} != "
            f"audited backtest trades {db_oos}. Live data has diverged "
            f"from the approved research book — investigate before "
            f"writing signals.")
    # 2. Book at go-live must be the seeded FLAT state.
    if open_seed is not None or pending_seed is not None:
        raise RuntimeError(
            f"SEED ASSERTION FAILED: book at {SEED_CHECK_DATE} = "
            f"open={open_seed} pending={pending_seed} but seed = FLAT. "
            f"Live data has diverged from the seeded signal file — "
            f"investigate before writing signals.")
    return len(replay_oos)


def write_scores(cur, invested, state, as_of, audit_path):
    cur.execute("DELETE FROM gold.strategy_ticker_scores WHERE strategy_id = %s", (SID,))
    rows = []
    if invested:
        rule = ("vix_z60 cross >=+2 (re-arm <1) -> next-day close GLD 50%/SPY 50%; "
                "time exit +20td; first event wins")
        for t, w in LEGS.items():
            rows.append((t, w, "BUY", {
                "weight": w,
                "event_date": str(state["event_date"]) if state.get("event_date") else None,
                "entry_date": str(state["entry_date"]) if state.get("entry_date") else None,
                "exit_date": str(state["exit_date"]) if state.get("exit_date") else None,
                "held_td": state.get("held_td"),
                "pending_entry": state.get("pending", False),
                "rule": rule,
                "audit_file": audit_path,
            }))
        rows.append(("CASH", 0.0, "HOLD", {
            "weight": 0.0,
            "note": "fully invested crisis event (GLD/SPY 50/50)",
            "audit_file": audit_path,
        }))
    else:
        rows.append(("CASH", 1.0, "HOLD", {
            "weight": 1.0,
            "note": "flat by design — no active VIX-spike event "
                    "(event-driven book, in-market 22-28% of days)",
            "audit_file": audit_path,
        }))
        for t in LEGS:
            rows.append((t, 0.0, "HOLD", {
                "weight": 0.0,
                "note": "no active event",
                "audit_file": audit_path,
            }))
    for ticker, w, action, crit in rows:
        score = round(w * 100, 4)
        cur.execute(
            """
            INSERT INTO gold.strategy_ticker_scores
              (strategy_id, ticker, score, signal_action, entry_score, exit_score,
               criteria_met, position_status, deployed_at, updated_at, signal_source)
            VALUES (%s, %s, %s, %s, %s, 0.0, %s::jsonb, 'PAPER', NOW(), NOW(),
                    'computed');
            """,
            (SID, ticker, score, action, score, json.dumps(crit)),
        )
    return rows


def write_signal_logs(cur, rows, as_of):
    cur.execute(
        "DELETE FROM consumption.signal_logs WHERE strategy_id = %s AND signal_date = %s",
        (SID, as_of))
    for ticker, w, action, crit in rows:
        cur.execute(
            """
            INSERT INTO consumption.signal_logs
              (strategy_id, signal_date, signal, ticker, signal_type,
               signal_criteria, confidence)
            VALUES (%s, %s, 1, %s, %s, %s, %s);
            """,
            (SID, as_of, ticker, "BUY",
             f"weight={w}; rule=us_vix_spike_crisis_event_v3", round(w * 100, 4)),
        )


def touch_registry(cur, audit_path):
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET last_signal_at = NOW(), updated_at = NOW(), signal_file_path = %s
        WHERE strategy_id = %s;
        """,
        (audit_path, SID))
    return cur.rowcount


def record_agent_event(cur, summary):
    payload = {"strategy_id": SID, "agent_name": "qr_etl",
               "kanban_task_id": "t_de0986e1",
               "generated_at": datetime.now(timezone.utc).isoformat(), **summary}
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status,
           created_at, payload)
        VALUES ('signal_generated', %s, 'signals', 'etl-manager', %s::jsonb,
                'ok', NOW(), %s::jsonb);
        """,
        (SID, json.dumps(payload), json.dumps(payload)),
    )


def main():
    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        cur.execute(Z_SQL)
        z = [(d, float(v)) for d, v in cur.fetchall()]
        cur.execute(CAL_SQL)
        cal = [d for (d,) in cur.fetchall()]
        if not z or not cal:
            raise RuntimeError("empty vix_regime or GLD calendar — refusing to write")
        z_max, as_of = z[-1][0], cal[-1]
        if (date.today() - as_of).days > 4:
            print(f"WARNING: US prices stale (max GLD date {as_of}); "
                  f"signal computed as of {as_of}")
        if z_max < as_of:
            print(f"WARNING: gold.vix_regime lags prices (z max {z_max} < "
                  f"{as_of}) — fresh spikes cannot be detected; investigate ETL")

        evset = events_from(z)
        trades, open_pos, pending = replay(cal, evset)

        # hard gate BEFORE any write: replay must reproduce the audited book
        n_oos = assert_seed_state(cur, cal, evset)

        # current state
        invested = open_pos is not None or pending is not None
        state = {"pending": False}
        if open_pos is not None:
            trigger_d, entry_d, entry_i = open_pos
            exit_i = entry_i + HOLD_TD
            state = {
                "pending": False,
                "event_date": trigger_d,
                "entry_date": entry_d,
                "exit_date": cal[exit_i] if exit_i < len(cal) else None,
                "held_td": len(cal) - 1 - entry_i,
            }
        elif pending is not None:
            state = {"pending": True, "event_date": pending,
                     "entry_date": None, "exit_date": None, "held_td": 0}

        # OOS events that never triggered a trade and are not the trigger of
        # the active/pending position = first-wins overlap skips (engine:
        # `d in evset and not pos and pending is None` gates admission).
        triggered = {tr for tr, _, _ in trades}
        if open_pos is not None:
            triggered.add(open_pos[0])
        if pending is not None:
            triggered.add(pending)
        skipped_overlap = sorted(
            d for d in evset
            if OOS_START <= d <= as_of and d not in triggered)

        os.makedirs(AUDIT_DIR, exist_ok=True)
        audit_path = os.path.join(
            AUDIT_DIR, f"{SID}_signals_{as_of.isoformat()}.json")
        audit = {
            "strategy_id": SID,
            "name": "US VIX-Spike Crisis Event GLD/SPY 50/50 (vix_z60 cross >=+2, re-arm <1, enter next-day close, time exit +20td)",
            "as_of": as_of.isoformat(),
            "go_live": GO_LIVE.isoformat(),
            "trigger": {"trig": TRIG, "rearm": REARM, "hold_td": HOLD_TD},
            "weights_are_target_portfolio": True,
            "long_only": True,
            "state": ("PENDING_ENTRY" if state.get("pending")
                      else "INVESTED" if invested else "FLAT"),
            "signals": (
                {**{t: {"action": "BUY", "weight": w,
                        "entry_date": str(state["entry_date"]) if state.get("entry_date") else None,
                        "exit_date": str(state["exit_date"]) if state.get("exit_date") else None}
                    for t, w in LEGS.items()},
                 "CASH": {"action": "HOLD", "weight": 0.0}}
                if invested else
                {"CASH": {"action": "HOLD", "weight": 1.0},
                 **{t: {"action": "HOLD", "weight": 0.0} for t in LEGS}}),
            "diagnostics": {
                "z_latest": {"date": z_max.isoformat(), "vix_z60": z[-1][1]},
                "events_total_full_history": len(evset),
                "events_oos_window": sorted(
                    d.isoformat() for d in evset if OOS_START <= d <= as_of),
                "trades_full_history": len(trades),
                "trades_oos_replayed": [
                    {"trigger_date": tr.isoformat(),
                     "entry_date": e.isoformat(), "exit_date": x.isoformat()}
                    for tr, e, x in trades if OOS_START <= e <= as_of],
                "skipped_overlap_oos": [d.isoformat() for d in skipped_overlap],
                "open_position": (
                    {"entry_date": str(state.get("entry_date")),
                     "exit_date": str(state.get("exit_date")),
                     "held_td": state.get("held_td")}
                    if open_pos is not None else None),
                "pending_entry": state.get("pending", False),
                "seed_check": {"date": SEED_CHECK_DATE.isoformat(),
                               "expected": "FLAT, 6 OOS trades == backtest_trades",
                               "status": "PASS",
                               "oos_trades_matched": n_oos},
            },
        }
        with open(audit_path, "w") as f:
            json.dump(audit, f, indent=2)

        rows = write_scores(cur, invested, state, as_of, audit_path)
        write_signal_logs(cur, rows, as_of)
        n_reg = touch_registry(cur, audit_path)
        if n_reg != 1:
            raise RuntimeError(
                f"registry touch matched {n_reg} rows for {SID} (expected 1)")
        record_agent_event(cur, {
            "as_of": as_of.isoformat(),
            "state": audit["state"],
            "invested": invested,
            "pending_entry": state.get("pending", False),
            "events_oos_window": len(audit["diagnostics"]["events_oos_window"]),
            "audit_file": audit_path,
        })
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(f"[OK] {SID} as_of={as_of}: state={audit['state']} "
          f"events_oos={audit['diagnostics']['events_oos_window']} "
          f"skipped_overlap={[d for d in audit['diagnostics']['skipped_overlap_oos']]} "
          f"z_latest={z[-1][1]:+.4f}@{z_max} seed_check=PASS "
          f"(oos_trades_matched={n_oos})")
    if state.get("pending"):
        print(f"  PENDING ENTRY: event {state['event_date']} -> "
              f"GLD/SPY 50/50 fills next GLD bar close")
    elif open_pos is not None:
        print(f"  OPEN: entry {state['entry_date']} exit {state['exit_date']} "
              f"held {state['held_td']}/{HOLD_TD}td")


if __name__ == "__main__":
    main()
