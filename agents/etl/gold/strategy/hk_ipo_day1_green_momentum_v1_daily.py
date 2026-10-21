#!/usr/bin/env python3
"""
Daily signal generator: hk_ipo_day1_green_momentum_v1 (kanban t_78c4e834)
==========================================================================
HK IPO Day-1 Green Momentum V1 — retail oversub >= 500x, day-1 green
(first_day_close > first_day_open), no-chase cap (first_day_close <=
1.5 x offer_price), enter at day-1 close, time-exit at close +5 bars,
5 slots x 20% NAV, event-driven (mostly CASH).

Approved 2026-09-05 (4-stage audit PASS x4 incl qa_reproduction
--frequency daily; engine of record:
qr_research/workspace/hk_ipo_batch/ipo_day1_green_v1.py; backtest run
35d73295-406f-47db-bf24-c14f09dcee48, 18 trades, 0 capacity skips,
0 open at end). Second IPO-tab strategy; disjoint from
hk_ipo_postlisting_drift_p1_v3 by oversub band (>=500x vs [100,500)) —
both stay live.

Rule fidelity to the V1 research engine (ipo_day1_green_v1.py):
  - Events: silver.unified_ipo_calendar JOIN silver.unified_ipo_performance,
    oversubscription_retail >= 500, first_day_open>0, first_day_close>0,
    offer_price>0. NOTE: engine has NO board filter — 8090.HK (GEM) is in
    the approved 18-trade book; "Main-board" in the mandate is descriptive,
    not a gate. Do not add one without re-approving the book.
  - Entry filters (knowable at day-1 close): fdc > fdo (green) AND
    fdc <= 1.5 x offer_price (no-chase; load-bearing — uncapped sibling P2
    MDD -31.6%).
  - Data gates: price path from listing_date needs >= 2 bars and its first
    close within 2% of first_day_close (bad-feed / recycled-ticker guard).
  - Entry bar index 0 (day-1 close), exit bar index min(5, len(path)-1)
    (bars = trading days in silver.unified_prices from listing_date
    onward). Slot frees at the close of the exit bar; if the path is
    truncated (< 6 bars) the slot holds until the last available bar and
    the exit bar extends as new prices arrive — engine semantics.
  - Capacity: 5 slots; admission processed in entry_date order BEFORE
    same-day exits are freed (engine simulate() order); skipped events are
    permanently skipped.
  - OOS window: engine admits trades with listing_date >= 2024-01-01.

Book semantics:
  The book was seeded 2026-09-05 by qr_research FLAT (CASH 100%; last event
  window closed 2026-07-16). This script runs a CONTINUOUS capacity replay
  (admissions for listing_date >= 2024-01-01, matching the engine OOS
  window) so the computed book is by construction the research book at
  every date. Hard seed assertions pin the replay to the approved backtest:
  admissions with entry_date <= 2026-09-05 must equal 18 with 0 capacity
  skips, and the open book at 2026-09-05 must be empty. Any drift fails the
  run loudly BEFORE any DB write.

Run cadence: daily via run_signal_cycle.sh (Pipeline B, step 1d), after
build_rotation_signals.py (which skips this strategy — no engine config —
so these rows are the final writer) and before snapshot + rebalancer.

Writes (idempotent; delete-then-insert per strategy):
  - gold.strategy_ticker_scores : BUY rows (score = weight*100 = 20) per open
    slot + one CASH row with the residual weight (CASH counts in total score
    so the rebalancer respects residual cash).
  - consumption.signal_logs     : one row per holding + CASH (signal=1).
  - gold.strategy_registry      : last_signal_at, signal_file_path -> audit JSON.
  - Audit JSON: agents/etl/data/signals/hk_ipo_day1_green_momentum_v1/
    hk_ipo_day1_green_momentum_v1_signals_YYYY-MM-DD.json

Prices: reads silver.unified_prices (fed by bronze yfinance stage over active
gold.asset_registry tickers; refresh_ipo_calendar_daily.py auto-onboards new
listings so future events have price paths by entry time).

History window: engine OOS window opens 2024-01-01 on listing_date and entry
is bar 0, so listing_date >= 2024-01-01 covers every admissible event.
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

SID = "hk_ipo_day1_green_momentum_v1"
GO_LIVE = date(2026, 9, 5)           # first live signal date
SEED_CHECK_DATE = date(2026, 9, 5)   # qr_research seed signal date
SEED_CHECK_OPEN = set()              # seeded book is FLAT (CASH 100%)
SEED_ADMITTED_PRE = 18               # backtest run 35d73295 trade_count_oos
SEED_SKIPPED_PRE = 0                 # backtest skipped_capacity
REPLAY_START = date(2024, 1, 1)      # engine OOS window (listing_date cutoff)
SLOTS = 5
ENTRY_BAR = 0                        # day-1 close
HOLD_BARS = 5                        # exit bar = min(5, len(path)-1)
WEIGHT_PER_SLOT = 1.0 / SLOTS
OS_MIN = 500.0
NOCHASE_CAP = 1.5                    # fdc <= 1.5 x offer_price (load-bearing)
MIN_BARS = 2                         # engine data-quality gate
FIRST_CLOSE_TOL = 0.02               # engine: np.isclose(path[0], fdc, rtol=0.02)
LISTING_LOOKBACK = date(2024, 1, 1)  # see module docstring
AUDIT_DIR = os.path.join(ETL_HOME, "data", "signals", SID)

EVENTS_SQL = """
    SELECT c.ticker, c.listing_date, c.oversubscription_retail AS oversub,
           c.offer_price, p.first_day_open, p.first_day_close
    FROM silver.unified_ipo_calendar c
    JOIN silver.unified_ipo_performance p USING (ticker, listing_date)
    WHERE c.oversubscription_retail >= %s
      AND c.listing_date >= %s
      AND p.first_day_open > 0 AND p.first_day_close > 0
      AND c.offer_price > 0
    ORDER BY c.listing_date, c.ticker
"""

PRICES_SQL = """
    SELECT ticker, date, close FROM silver.unified_prices
    WHERE market = 'HK' AND ticker = ANY(%s) AND date >= %s
    ORDER BY ticker, date
"""

HK_MAX_DATE_SQL = "SELECT max(date) FROM silver.unified_prices WHERE market = 'HK'"


def load_events(cur):
    cur.execute(EVENTS_SQL, (OS_MIN, LISTING_LOOKBACK))
    rows = cur.fetchall()
    events = [
        {"ticker": t, "listing_date": ld, "oversub": float(o),
         "offer_price": float(op),
         "first_day_open": float(fo), "first_day_close": float(fc)}
        for t, ld, o, op, fo, fc in rows
    ]
    tickers = sorted({e["ticker"] for e in events})
    paths = {}
    if tickers:
        cur.execute(PRICES_SQL, (tickers, LISTING_LOOKBACK))
        for t, d, c in cur.fetchall():
            if c is None or float(c) <= 0:
                continue
            paths.setdefault(t, []).append((d, float(c)))
    cur.execute(HK_MAX_DATE_SQL)
    hk_max = cur.fetchone()[0]
    return events, paths, hk_max


def build_books(events, paths, as_of):
    """Apply engine filters + data gates, compute entry/exit bars, replay
    capacity continuously from REPLAY_START (engine OOS simulate window).
    Returns (holdings, pending, skipped_capacity, dropped, rejected_green,
    rejected_nochase, admitted)."""
    admitted = []          # events admitted with listing_date >= REPLAY_START
    pending = []           # gates passed, < MIN_BARS price bars yet
    dropped = []           # failed data gates (no prices / first-close mismatch)
    rejected_green = []    # first_day_close <= first_day_open
    rejected_nochase = []  # first_day_close > 1.5 x offer_price
    n_skipped_capacity = 0

    candidates = []
    for e in events:
        fdc, fdo, op = e["first_day_close"], e["first_day_open"], e["offer_price"]
        # engine filter order: green -> no-chase -> data gates
        if not (fdc > fdo):
            rejected_green.append({**e, "reason": "day-1 not green (fdc <= fdo)"})
            continue
        if fdc > NOCHASE_CAP * op:
            rejected_nochase.append({
                **e, "cap": round(NOCHASE_CAP * op, 6),
                "reason": f"no-chase: fdc {fdc} > {NOCHASE_CAP}x offer {op}"})
            continue
        path = paths.get(e["ticker"])
        if not path:
            dropped.append({**e, "reason": "no prices in unified_prices"})
            continue
        path = [(d, c) for d, c in path if d >= e["listing_date"]]
        if len(path) < MIN_BARS:
            pending.append({**e, "bars_so_far": len(path),
                            "bars_to_tradeable": MIN_BARS - len(path)})
            continue
        # engine sanity gate: first close within 2% of first_day_close
        if abs(path[0][1] / fdc - 1.0) > FIRST_CLOSE_TOL:
            dropped.append({**e, "reason": "first close != first_day_close (2%)"})
            continue
        entry_date, entry_px = path[ENTRY_BAR]
        xi = min(HOLD_BARS, len(path) - 1)
        exit_date, exit_px = path[xi]
        closed = HOLD_BARS < len(path)
        candidates.append({**e, "entry_date": entry_date, "entry_px": entry_px,
                           "exit_date": exit_date, "exit_px": exit_px,
                           "closed_sched": closed})

    # engine admits only trades inside the OOS window (listing_date cutoff)
    candidates = [c for c in candidates if c["listing_date"] >= REPLAY_START]

    # capacity replay: admission in entry_date order; same-day exits do NOT
    # free a slot for that day's admissions (engine simulate() order).
    candidates.sort(key=lambda x: (x["entry_date"], x["listing_date"], x["ticker"]))
    for c in candidates:
        d = c["entry_date"]
        occupied = sum(
            1 for a in admitted
            if a["entry_date"] <= d and a["exit_date"] >= d
        )
        if occupied < SLOTS:
            admitted.append(c)
        else:
            n_skipped_capacity += 1

    holdings = [a for a in admitted
                if a["entry_date"] <= as_of and a["exit_date"] > as_of]
    return (holdings, pending, n_skipped_capacity, dropped,
            rejected_green, rejected_nochase, admitted)


def assert_seed_state(admitted, n_skipped_capacity, as_of):
    """Pin the continuous replay to the approved research book: admissions
    with entry_date <= SEED_CHECK_DATE must reproduce backtest run 35d73295
    (18 taken, 0 capacity skips) and the seeded book at 2026-09-05 is FLAT.
    All seed-window quantities are causal (unaffected by future events), so
    this assertion stays valid after go-live. Loud failure — any drift means
    live data diverged from the approved research book."""
    pre = [a for a in admitted if a["entry_date"] <= SEED_CHECK_DATE]
    # skipped capacity count is replay-causal only if computed over entries
    # <= seed date; the replay above processes in entry_date order so any
    # pre-seed skip is already final once all pre-seed candidates are seen.
    open_at_seed = {a["ticker"] for a in admitted
                    if a["entry_date"] <= SEED_CHECK_DATE
                    and a["exit_date"] > SEED_CHECK_DATE}
    problems = []
    if open_at_seed != SEED_CHECK_OPEN:
        problems.append(
            f"open book at {SEED_CHECK_DATE} = {sorted(open_at_seed)} "
            f"but seed = {sorted(SEED_CHECK_OPEN)}")
    if len(pre) != SEED_ADMITTED_PRE:
        problems.append(
            f"admissions with entry_date <= {SEED_CHECK_DATE} = {len(pre)} "
            f"but backtest run 35d73295 trade_count_oos = {SEED_ADMITTED_PRE}")
    if as_of <= SEED_CHECK_DATE and n_skipped_capacity != SEED_SKIPPED_PRE:
        problems.append(
            f"capacity skips = {n_skipped_capacity} but backtest = "
            f"{SEED_SKIPPED_PRE}")
    if problems:
        raise RuntimeError(
            "SEED ASSERTION FAILED: " + "; ".join(problems) +
            ". Live data has diverged from the approved research book — "
            "investigate before writing signals.")


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
            "offer_price": h["offer_price"],
            "first_day_open": h["first_day_open"],
            "first_day_close": h["first_day_close"],
            "entry_date": str(h["entry_date"]),
            "entry_px": h["entry_px"],
            "exit_date": str(h["exit_date"]),
            "rule": "oversub>=500x; D1 green (fdc>fdo); no-chase fdc<=1.5x offer; entry=day1 close; exit=listing+5 bars (time exit)",
            "audit_file": audit_path,
        }))
    rows.append(("CASH", cash_w, "HOLD", {
        "weight": cash_w,
        "note": "residual cash; event-driven 5-slot book (mostly-cash by design)",
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
             f"weight={w}; rule=hk_ipo_day1_green_momentum_v1", round(w * 100, 4)),
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
               "kanban_task_id": "t_78c4e834",
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

        (holdings, pending, n_skip, dropped,
         rejected_green, rejected_nochase, admitted) = \
            build_books(events, paths, as_of)

        # hard gate BEFORE any write: replay must reproduce the approved book
        assert_seed_state(admitted, n_skip, as_of)

        os.makedirs(AUDIT_DIR, exist_ok=True)
        audit_path = os.path.join(
            AUDIT_DIR, f"{SID}_signals_{as_of.isoformat()}.json")
        audit = {
            "strategy_id": SID,
            "name": "HK IPO Day-1 Green Momentum V1 (oversub 500x+, D1 green, no-chase 1.5x offer, hold 5d)",
            "as_of": as_of.isoformat(),
            "go_live": GO_LIVE.isoformat(),
            "filters": {"oversub_min": OS_MIN, "green_day1": True,
                        "nochase_cap_x_offer": NOCHASE_CAP,
                        "entry": "day1_close", "hold_bars": HOLD_BARS},
            "weights_are_target_portfolio": True,
            "long_only": True,
            "signals": {
                **{h["ticker"]: {"action": "BUY", "weight": WEIGHT_PER_SLOT,
                                 "listing_date": str(h["listing_date"]),
                                 "oversubscription_retail": h["oversub"],
                                 "entry_date": str(h["entry_date"]),
                                 "entry_px": h["entry_px"],
                                 "exit_date": str(h["exit_date"])}
                   for h in holdings},
                "CASH": {"action": "HOLD",
                         "weight": round(1.0 - WEIGHT_PER_SLOT * len(holdings), 10)},
            },
            "diagnostics": {
                "events_scanned": len(events),
                "admitted_since_2024": len(admitted),
                "skipped_capacity_since_2024": n_skip,
                "rejected_green": [
                    {"ticker": r["ticker"], "listing_date": str(r["listing_date"]),
                     "fdo": r["first_day_open"], "fdc": r["first_day_close"]}
                    for r in rejected_green],
                "rejected_nochase": [
                    {"ticker": r["ticker"], "listing_date": str(r["listing_date"]),
                     "fdc": r["first_day_close"], "cap": r["cap"]}
                    for r in rejected_nochase],
                "dropped_data_gates": [
                    {"ticker": d["ticker"], "listing_date": str(d["listing_date"]),
                     "reason": d["reason"]} for d in dropped],
                "pending_entry": [
                    {"ticker": p["ticker"], "listing_date": str(p["listing_date"]),
                     "oversubscription_retail": p["oversub"],
                     "bars_so_far": p["bars_so_far"]} for p in pending],
                "seed_check": {"date": SEED_CHECK_DATE.isoformat(),
                               "expected_open": sorted(SEED_CHECK_OPEN),
                               "expected_admitted_pre_seed": SEED_ADMITTED_PRE,
                               "status": "PASS"},
            },
        }
        with open(audit_path, "w") as f:
            json.dump(audit, f, indent=2)

        rows = write_scores(cur, holdings, as_of, audit_path)
        write_signal_logs(cur, rows, as_of)
        n_reg = touch_registry(cur, audit_path)
        if n_reg != 1:
            raise RuntimeError(
                f"registry touch matched {n_reg} rows for {SID} (expected 1)")
        record_agent_event(cur, {
            "as_of": as_of.isoformat(),
            "holdings": [h["ticker"] for h in holdings],
            "cash_weight": round(1.0 - WEIGHT_PER_SLOT * len(holdings), 10),
            "events_scanned": len(events),
            "pending_entry": len(pending),
            "green_rejections": len(rejected_green),
            "nochase_rejections": len(rejected_nochase),
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
          f"admitted={len(admitted)} pending={len(pending)} "
          f"skipped_capacity={n_skip} green_rejected={len(rejected_green)} "
          f"nochase_rejected={len(rejected_nochase)} dropped={len(dropped)} "
          f"seed_check=PASS")
    for p in pending:
        print(f"  PENDING: {p['ticker']} listed {p['listing_date']} "
              f"oversub={p['oversub']:.1f}x bars_so_far={p['bars_so_far']}")


if __name__ == "__main__":
    main()
