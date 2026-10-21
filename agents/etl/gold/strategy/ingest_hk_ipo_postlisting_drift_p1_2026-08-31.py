#!/usr/bin/env python3
"""
WRITE_SIGNAL: hk_ipo_postlisting_drift_p1 onboarding (kanban 5711f0bb)
2026-08-31

Strategy: HK IPO Post-Listing Drift (oversub 100-500x, enter listing+20d,
hold 20d, 5 x 20% NAV slots, event-driven, mostly CASH). 4-stage audit
PASS x4 by qr_research; --frequency daily; PAPER / EXPERIMENTAL.

Manifest (validated --check-db by qr_research):
  /home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_handoff_manifest_20260831.json
Signal file (as_of 2026-08-31 = 100% CASH, no qualifying events):
  /home/ubuntu/.hermes/profiles/qr_research/workspace/hk_ipo_batch/hk_ipo_postlisting_drift_p1_signals_2026-08-31.json

Research already wrote: gold.strategy_research, gold.strategy_backtest_runs,
gold.strategy_registry (status=paper, execution_mode=PAPER,
priority=EXPERIMENTAL, signal_file_path set).

This script (ETL side, mirrors ingest_batch12_2026-08-05.py convention):

  1. gold.asset_registry    - onboard the 51 universe tickers (all present in
                              silver.unified_ipo_calendar; latest listing per
                              ticker). is_active=TRUE so the daily bronze
                              yfinance stage (universe = active registry
                              tickers) picks up their prices.
  2. gold.strategy_ticker_scores - current signal is 100% CASH: single CASH
                              HOLD row, score=100.00 (weight*100 convention so
                              rebuild_paper_positions reproduces target
                              weights). No BUY rows today.
  3. consumption.signal_logs - one CASH row for today (signal=1, BUY,
                              weight=1.0; source=<signal file>, conf=100)
                              matching existing CASH-row convention.
  4. gold.strategy_configs  - paper_design declaration (slot_count=5,
                              design_max_position_pct=0.2) so the rebalancer
                              cap source is declared, not a WARNING fallback.
  5. gold.agent_events      - audit row.

NOT written here:
  - gold.signal_evaluations: rebuilt by signals/strategies/build_signal_redesign.py
    from strategy_ticker_scores (BUY/SELL only; all-CASH emits nothing, which
    is the honest quiet state). Explicit family branch 'hk_ipo_postlisting'
    -> 'momentum' added there (manifest signal_family=momentum would otherwise
    fall through to the generic 'drift'->'trend' keyword).
  - gold.strategy_signal_criteria: not populated for signal-file strategies
    (batch10/11/12 precedent); the table serves rule-based computed strategies
    (S9_MACD). signal_file_path in gold.strategy_registry is the mechanism.

Idempotent on re-run (upserts / delete-then-insert per strategy+date).

Known flags handed to VERIFY (not silently fixed here):
  - registry assigned_capital=10000 vs manifest 50000 (EXPERIMENTAL half-size
    may be intentional; qr_risk owns final allocation).
  - silver.unified_ipo_calendar: 2451.HK is a recycled ticker (two listings;
    qualifying row is GreenTech 2024-03-20, 125.60x).
"""
import os
import sys
import json
from datetime import datetime, date

import pytz

ETL_HOME = os.path.expanduser(
    "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl"
)
SHARED = os.path.join(ETL_HOME, "shared", "scripts")
if SHARED not in sys.path:
    sys.path.insert(0, SHARED)

from db import get_connection  # noqa: E402

HKT = pytz.timezone("Asia/Hong_Kong")
TASK_ID = "5711f0bb-7d47-4a26-b3c2-91ebe1dd3cc3"
BATCH_ID = "hk-ipo-batch-2026-08-30"
SID = "hk_ipo_postlisting_drift_p1"
SIGNAL_FILE = ("/home/ubuntu/.hermes/profiles/qr_research/workspace/"
               "hk_ipo_batch/hk_ipo_postlisting_drift_p1_signals_2026-08-31.json")

UNIVERSE = [
    "2451.HK","2509.HK","2497.HK","2515.HK","2438.HK","2505.HK","2443.HK",
    "2550.HK","2522.HK","2228.HK","2559.HK","1354.HK","2576.HK","9639.HK",
    "2460.HK","1588.HK","1364.HK","2569.HK","9606.HK","1333.HK","6831.HK",
    "3750.HK","1276.HK","9881.HK","2605.HK","2508.HK","3880.HK","2651.HK",
    "2525.HK","9973.HK","2259.HK","6166.HK","9927.HK","2788.HK","2408.HK",
    "3887.HK","2635.HK","2671.HK","6600.HK","9903.HK","3200.HK","0600.HK",
    "3268.HK","2701.HK","2476.HK","1187.HK","2493.HK","1081.HK","3661.HK",
    "2672.HK","6915.HK",
]


def now_hkt():
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_signal_payload():
    with open(SIGNAL_FILE) as f:
        return json.load(f)


def onboard_asset_registry(cur):
    """Insert the 51 universe tickers from silver.unified_ipo_calendar.
    Recycled tickers: take the LATEST listing row (ROW_NUMBER)."""
    cur.execute(
        """
        WITH latest AS (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY ticker
                                         ORDER BY listing_date DESC) rn
            FROM silver.unified_ipo_calendar
            WHERE ticker = ANY(%s)
        )
        INSERT INTO gold.asset_registry
          (ticker, name, asset_class, market, horizon, is_active,
           sector, description, created_at, updated_at)
        SELECT
          ticker,
          stock_name,
          'STOCK',
          'HK',
          '1d',
          TRUE,
          sector,
          'HK IPO universe (hk_ipo_postlisting_drift_p1, kanban ' || %s || '); '
          || 'listed ' || listing_date || ' on ' || COALESCE(board, '?')
          || ' board; retail oversub '
          || COALESCE(oversubscription_retail::text, 'n/a') || 'x',
          NOW(), NOW()
        FROM latest
        WHERE rn = 1
        ON CONFLICT (ticker) DO UPDATE SET
          name       = EXCLUDED.name,
          is_active  = TRUE,
          sector     = COALESCE(gold.asset_registry.sector, EXCLUDED.sector),
          updated_at = NOW();
        """,
        (UNIVERSE, TASK_ID),
    )
    return cur.rowcount


def wire_ticker_scores(cur, payload):
    """Current signal: 100% CASH. score = weight*100 (target-weight convention)."""
    cur.execute(
        "DELETE FROM gold.strategy_ticker_scores WHERE strategy_id = %s", (SID,))
    cash = payload["signals"].get("CASH", {})
    w = float(cash.get("weight", 1.0))
    cur.execute(
        """
        INSERT INTO gold.strategy_ticker_scores
          (strategy_id, ticker, score, signal_action, entry_score, exit_score,
           criteria_met, position_status, deployed_at, updated_at, signal_source)
        VALUES (%s, 'CASH', %s, 'HOLD', %s, 0.0, %s::jsonb, 'PAPER',
                NOW(), NOW(), 'computed');
        """,
        (SID, round(w * 100, 4), round(w * 100, 4), json.dumps({
            "weight": w,
            "source_signal_file": SIGNAL_FILE,
            "as_of": payload.get("as_of"),
            "batch_id": BATCH_ID,
            "note": "all-cash: no qualifying IPO events in entry window "
                    "(oversub 100-500x, listing+20d); event-driven book",
            "kanban_task_id": TASK_ID,
            "ingested_at": datetime.now(HKT).isoformat(),
        })),
    )
    return 1


def insert_signal_log(cur, payload):
    today = date.today()
    cur.execute(
        "DELETE FROM consumption.signal_logs WHERE strategy_id = %s AND signal_date = %s",
        (SID, today))
    cash = payload["signals"].get("CASH", {})
    w = float(cash.get("weight", 1.0))
    cur.execute(
        """
        INSERT INTO consumption.signal_logs
          (strategy_id, signal_date, signal, ticker, signal_type,
           signal_criteria, confidence)
        VALUES (%s, %s, 1, 'CASH', 'BUY', %s, %s);
        """,
        (SID, today,
         f"weight={w}; source={SIGNAL_FILE}", round(w * 100, 4)),
    )
    return 1


def declare_paper_design(cur):
    cur.execute(
        """
        INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value)
        VALUES (%s, 'paper_design', %s::jsonb)
        ON CONFLICT (strategy_id, config_key) DO UPDATE SET
          config_value = EXCLUDED.config_value;
        """,
        (SID, json.dumps({
            "weighting": "event-driven 5-slot book, 20% NAV per slot; slots fill "
                         "on qualifying IPO events (retail oversub 100-500x, entry "
                         "listing+20d close), time-exit +20d; mostly CASH between "
                         "events (avg gross ~31% by design)",
            "slot_count": 5,
            "declared_at": "2026-08-31",
            "declared_by": TASK_ID,
            "design_source": "gold.strategy_research.position_sizing "
                             "(slots=5, weight_per_slot=0.2); manifest "
                             "strategy_handoff_manifest_20260831.json",
            "residual_cash_policy": "unused slot capital parks in CASH (event-driven "
                                    "design; no forced deployment)",
            "design_max_position_pct": 0.2,
        })),
    )
    return 1


def touch_registry(cur):
    cur.execute(
        """
        UPDATE gold.strategy_registry
        SET last_signal_at = NOW(), updated_at = NOW()
        WHERE strategy_id = %s;
        """,
        (SID,))
    return cur.rowcount


def record_agent_event(cur, summary):
    payload = {
        "batch_id": BATCH_ID,
        "kanban_task_id": TASK_ID,
        "strategy_id": SID,
        "signal_file": SIGNAL_FILE,
        "agent_name": "qr_etl",
        "ingested_at": datetime.now(HKT).isoformat(),
        **summary,
    }
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status,
           created_at, payload)
        VALUES (%s, %s, 'etl', 'etl-manager', %s::jsonb, 'ok', NOW(), %s::jsonb);
        """,
        ("signal_ingested", SID, json.dumps(payload), json.dumps(payload)),
    )


def main():
    payload = load_signal_payload()
    sigs = payload.get("signals", {})
    buys = {t: e for t, e in sigs.items()
            if isinstance(e, dict) and e.get("action") == "BUY"
            and float(e.get("weight", 0)) > 0}
    if buys:
        raise SystemExit(
            f"{SID}: signal file contains BUY weights {list(buys)} — this "
            f"onboarding script handles the documented all-CASH state only; "
            f"extend before re-running.")
    if payload.get("as_of") != "2026-08-31":
        print(f"  WARNING: signal file as_of={payload.get('as_of')} "
              f"(expected 2026-08-31)")

    conn = get_connection()
    conn.autocommit = False
    try:
        cur = conn.cursor()
        n_reg = onboard_asset_registry(cur)
        n_scores = wire_ticker_scores(cur, payload)
        n_logs = insert_signal_log(cur, payload)
        declare_paper_design(cur)
        n_touch = touch_registry(cur)
        summary = {
            "asset_registry_upserted": n_reg,
            "ticker_score_rows": n_scores,
            "signal_log_rows": n_logs,
            "registry_touched": n_touch,
            "signal_state": "100% CASH (no qualifying events)",
        }
        record_agent_event(cur, summary)
        conn.commit()
        print(f"{now_hkt()} [OK] {SID}: asset_registry +{n_reg}, "
              f"ticker_scores={n_scores} (CASH 100%), signal_logs={n_logs}, "
              f"paper_design declared, registry touched={n_touch}")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
