#!/usr/bin/env python3
"""
Daily signal generator: hk_ipo_postlisting_drift_p1 (kanban 5711f0bb)
=====================================================================
HK IPO Post-Listing Drift — oversub 100-500x, enter close at listing+20 bars,
time-exit close at +40 bars, 5 slots x 20% NAV, event-driven (mostly CASH).

Approved 2026-08-31 (4-stage audit PASS x4; engine of record:
qr_research/workspace/hk_ipo_batch/ipo_pulse_portfolio.py). This script is the
LIVE daily scanner required by the handoff manifest risk flag: "Universe is
dynamic; signal engine must query new qualifying events, not just the static
51-ticker historical universe."

Rule fidelity to the research engine (ipo_pulse_portfolio.py):
  - Events: silver.unified_ipo_calendar JOIN silver.unified_ipo_performance,
    oversubscription_retail >= 100 (P1 keeps [100,500)), first_day_open>0,
    first_day_close>0.
  - Data gates: price path from listing_date needs >= 10 bars and its first
    close must be within 2% of first_day_close (bad-feed / recycled-ticker
    guard).
  - Entry bar index 20, exit bar index 40 (bars = trading days in
    silver.unified_prices from listing_date onward).
  - Capacity: 5 slots; admission processed in entry_date order BEFORE same-day
    exits are freed (engine simulate() order); skipped events are permanently
    skipped.

Go-live semantics (decision documented for VERIFY):
  GO_LIVE = 2026-08-31 (date of the first approved signal). The paper book
  starts FLAT: events whose entry bar fired before GO_LIVE are never admitted
  (back-entering 3+ weeks late at a different price is NOT the backtested
  rule). Events with entry_date >= GO_LIVE participate in capacity replay
  from an empty book. At go-live this yields 100% CASH, matching the approved
  signal file. Five P1 events that entered 2026-08-04..08-07 (pre-go-live)
  are reported in the audit JSON as pre_golive_open_events for transparency.

Run cadence: daily via run_signal_cycle.sh (Pipeline B), after
build_rotation_signals.py (which skips this strategy — no engine config —
so these rows are the final writer) and before snapshot + rebalancer.

Writes (idempotent; delete-then-insert per strategy):
  - gold.strategy_ticker_scores : BUY rows (score = weight*100 = 20) per open
    slot + one CASH row with the residual weight (CASH counts in total score
    so the rebalancer respects residual cash).
  - consumption.signal_logs     : one row per holding + CASH (signal=1).
  - gold.strategy_registry      : last_signal_at, signal_file_path -> audit JSON.
  - Audit JSON: agents/etl/data/signals/hk_ipo_postlisting_drift_p1/
    hk_ipo_postlisting_drift_p1_signals_YYYY-MM-DD.json

Prices: reads silver.unified_prices (fed by bronze yfinance stage over active
gold.asset_registry tickers; refresh_ipo_calendar_daily.py auto-onboards new
listings so future events have price paths by entry time).

History window: only events that can still matter are loaded —
listing_date >= GO_LIVE - 75 days (entry bar 20 <= ~35 calendar days after
listing, so anything older can never have entry_date >= GO_LIVE).
"""
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone

ETL_HOME = os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl")
sys.path.insert(0, os.path.join(ETL_HOME, "shared", "scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")

from db import get_connection  # noqa: E402

SID = "hk_ipo_postlisting_drift_p1"
GO_LIVE = date(2026, 8, 31)          # first approved signal date; book starts flat
SLOTS = 5
ENTRY_BAR = 20
EXIT_BAR = 40
WEIGHT_PER_SLOT = 1.0 / SLOTS
MIN_BARS = 10                        # engine data-quality gate
LISTING_LOOKBACK_DAYS = 75           # see module docstring
AUDIT_DIR = os.path.join(ETL_HOME, "data", "signals", SID)

EVENTS_SQL = """
    SELECT c.ticker, c.listing_date, c.oversubscription_retail AS oversub,
           p.first_day_open, p.first_day_close
    FROM silver.unified_ipo_calendar c
    JOIN silver.unified_ipo_performance p USING (ticker, listing_date)
    WHERE c.oversubscription_retail >= 100
      AND c.oversubscription_retail < 500
      AND c.listing_date >= %s
      AND p.first_day_open > 0 AND p.first_day_close > 0
    ORDER BY c.listing_date, c.ticker
"""

PRICES_SQL = """
    SELECT ticker, date, close FROM silver.unified_prices
    WHERE market = 'HK' AND ticker = ANY(%s) AND date >= %s
    ORDER BY ticker, date
"""

HK_MAX_DATE_SQL = "SELECT max(date) FROM silver.unified_prices WHERE market = 'HK'"


def load_events(cur):
    cutoff = GO_LIVE - timedelta(days=LISTING_LOOKBACK_DAYS)
    cur.execute(EVENTS_SQL, (cutoff,))
    rows = cur.fetchall()
    events = [
        {"ticker": t, "listing_date": ld, "oversub": float(o),
         "first_day_open": float(fo), "first_day_close": float(fc)}
        for t, ld, o, fo, fc in rows
    ]
    tickers = sorted({e["ticker"] for e in events})
    paths = {}
    if tickers:
        cur.execute(PRICES_SQL, (tickers, cutoff))
        for t, d, c in cur.fetchall():
            if c is None or float(c) <= 0:
                continue
            paths.setdefault(t, []).append((d, float(c)))
    cur.execute(HK_MAX_DATE_SQL)
    hk_max = cur.fetchone()[0]
    return events, paths, hk_max


def build_books(events, paths, as_of):
    """Apply engine gates, compute entry/exit bars, replay capacity from
    GO_LIVE. Returns (holdings, pending, skipped_capacity, dropped, pre_golive)."""
    admitted = []   # events admitted since GO_LIVE (entry_date >= GO_LIVE)
    pending = []    # gates passed, entry bar not reached yet
    dropped = []    # failed data gates
    pre_golive = []  # entered before GO_LIVE, would still be open in a
                     # continuous book (informational only)
    n_skipped_capacity = 0

    candidates = []
    for e in events:
        path = paths.get(e["ticker"])
        if not path:
            dropped.append({**e, "reason": "no prices in unified_prices"})
            continue
        path = [(d, c) for d, c in path if d >= e["listing_date"]]
        if len(path) < MIN_BARS:
            dropped.append({**e, "reason": f"<{MIN_BARS} bars ({len(path)})"})
            continue
        # engine sanity gate: first close within 2% of first_day_close
        if abs(path[0][1] / e["first_day_close"] - 1.0) > 0.02:
            dropped.append({**e, "reason": "first close != first_day_close (2%)"})
            continue
        entry_date = path[ENTRY_BAR][0] if len(path) > ENTRY_BAR else None
        exit_date = path[EXIT_BAR][0] if len(path) > EXIT_BAR else None
        if entry_date is None:
            pending.append({**e, "bars_so_far": len(path),
                            "bars_to_entry": ENTRY_BAR - len(path) + 1})
            continue
        if entry_date < GO_LIVE:
            if exit_date is None or exit_date > as_of:
                pre_golive.append({**e, "entry_date": entry_date,
                                   "exit_date": exit_date})
            continue
        candidates.append({**e, "entry_date": entry_date, "exit_date": exit_date})

    # capacity replay: admission in entry_date order; same-day exits do NOT
    # free a slot for that day's admissions (engine simulate() order).
    candidates.sort(key=lambda x: (x["entry_date"], x["listing_date"], x["ticker"]))
    for c in candidates:
        d = c["entry_date"]
        occupied = sum(
            1 for a in admitted
            if a["entry_date"] <= d and (a["exit_date"] is None or a["exit_date"] >= d)
        )
        if occupied < SLOTS:
            admitted.append(c)
        else:
            n_skipped_capacity += 1

    holdings = [a for a in admitted
                if a["entry_date"] <= as_of
                and (a["exit_date"] is None or a["exit_date"] > as_of)]
    return holdings, pending, n_skipped_capacity, dropped, pre_golive, admitted


def write_scores(cur, holdings, as_of, audit_path):
    cur.execute("DELETE FROM gold.strategy_ticker_scores WHERE strategy_id = %s", (SID,))
    rows = []
    invested = WEIGHT_PER_SLOT * len(holdings)
    cash_w = round(1.0 - invested, 10)
    for h in holdings:
        rows.append((h["ticker"], WEIGHT_PER_SLOT, "BUY", {
            "weight": WEIGHT_PER_SLOT,
            "listing_date": str(h["listing_date"]),
            "oversubscription_retail": h["oversub"],
            "entry_date": str(h["entry_date"]),
            "exit_date": str(h["exit_date"]) if h["exit_date"] else None,
            "rule": "oversub[100,500); entry=listing+20 bars; exit=+40 bars (time exit)",
            "audit_file": audit_path,
        }))
    rows.append(("CASH", cash_w, "HOLD" if cash_w > 0 else "HOLD", {
        "weight": cash_w,
        "note": "residual cash; event-driven 5-slot book (avg gross ~31% by design)",
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
            (SID, as_of, ticker, "BUY" if action == "BUY" else "BUY",
             f"weight={w}; rule=hk_ipo_postlisting_drift_p1", round(w * 100, 4)),
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
               "kanban_task_id": "5711f0bb-7d47-4a26-b3c2-91ebe1dd3cc3",
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
        events, paths, hk_max = load_events(cur)
        as_of = hk_max or date.today()
        if (date.today() - as_of).days > 4:
            print(f"WARNING: HK prices stale (max date {as_of}); "
                  f"signal computed as of {as_of}")

        holdings, pending, n_skip, dropped, pre_golive, admitted = \
            build_books(events, paths, as_of)

        os.makedirs(AUDIT_DIR, exist_ok=True)
        audit_path = os.path.join(
            AUDIT_DIR, f"{SID}_signals_{as_of.isoformat()}.json")
        audit = {
            "strategy_id": SID,
            "name": "HK IPO Post-Listing Drift (oversub 100-500x, enter +20d, hold 20d)",
            "as_of": as_of.isoformat(),
            "go_live": GO_LIVE.isoformat(),
            "weights_are_target_portfolio": True,
            "long_only": True,
            "signals": {
                **{h["ticker"]: {"action": "BUY", "weight": WEIGHT_PER_SLOT,
                                 "listing_date": str(h["listing_date"]),
                                 "oversubscription_retail": h["oversub"],
                                 "entry_date": str(h["entry_date"]),
                                 "exit_date": str(h["exit_date"]) if h["exit_date"] else None}
                   for h in holdings},
                "CASH": {"action": "HOLD",
                         "weight": round(1.0 - WEIGHT_PER_SLOT * len(holdings), 10)},
            },
            "diagnostics": {
                "events_scanned": len(events),
                "admitted_since_golive": len(admitted),
                "skipped_capacity_since_golive": n_skip,
                "dropped_data_gates": [
                    {"ticker": d["ticker"], "listing_date": str(d["listing_date"]),
                     "reason": d["reason"]} for d in dropped],
                "pending_entry": [
                    {"ticker": p["ticker"], "listing_date": str(p["listing_date"]),
                     "oversubscription_retail": p["oversub"],
                     "bars_so_far": p["bars_so_far"],
                     "bars_to_entry": p["bars_to_entry"]} for p in pending],
                "pre_golive_open_events": [
                    {"ticker": p["ticker"], "listing_date": str(p["listing_date"]),
                     "oversubscription_retail": p["oversub"],
                     "entry_date": str(p["entry_date"]),
                     "exit_date": str(p["exit_date"]) if p["exit_date"] else None}
                    for p in pre_golive],
            },
        }
        with open(audit_path, "w") as f:
            json.dump(audit, f, indent=2)

        rows = write_scores(cur, holdings, as_of, audit_path)
        write_signal_logs(cur, rows, as_of)
        n_reg = touch_registry(cur, audit_path)
        record_agent_event(cur, {
            "as_of": as_of.isoformat(),
            "holdings": [h["ticker"] for h in holdings],
            "cash_weight": round(1.0 - WEIGHT_PER_SLOT * len(holdings), 10),
            "events_scanned": len(events),
            "pending_entry": len(pending),
            "audit_file": audit_path,
        })
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    invested_pct = WEIGHT_PER_SLOT * len(holdings) * 100
    print(f"[OK] {SID} as_of={as_of}: holdings={len(holdings)} "
          f"({[h['ticker'] for h in holdings]}) invested={invested_pct:.0f}% "
          f"cash={100 - invested_pct:.0f}% | events_scanned={len(events)} "
          f"pending_entry={len(pending)} skipped_capacity={n_skip} "
          f"dropped={len(dropped)} pre_golive_open={len(pre_golive)}")
    for p in pending:
        print(f"  PENDING: {p['ticker']} listed {p['listing_date']} "
              f"oversub={p['oversub']:.1f}x entry in ~{p['bars_to_entry']} bars")
    if pre_golive:
        print(f"  NOTE: {len(pre_golive)} qualifying events entered before "
              f"go-live ({GO_LIVE}) and were NOT back-entered "
              f"(book started flat; see audit JSON pre_golive_open_events).")


if __name__ == "__main__":
    main()
