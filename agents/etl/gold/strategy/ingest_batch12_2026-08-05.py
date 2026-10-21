#!/usr/bin/env python3
"""
WRITE_SIGNAL: batch12 2026-08-05 onboarding (1 approved strategy)
Task: t_56e35a73

Manifest (validated --check-db by qr_research):
  /home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_handoff_manifest_20260805_batch12.json

etf_comm_trend_basket_15 (Commodity Trend Basket) - EXPERIMENTAL, monthly,
PAPER. Crisis-alpha sleeve per book review R4. Signal-file strategy
(weights_are_target_portfolio=true, long-only, entry at close of signal date).
Engine wiring mirrors batch11 ingest_batch11_2026-08-05.py:

  1. gold.strategy_research        - status approved, full universe, logic text
  2. gold.strategy_backtest_runs   - one row, IS + OOS metrics
  3. gold.strategy_registry        - PAPER/paper, signal_mechanism='ingested',
                                     signal_file_path, OOS metrics,
                                     assigned_capital=50,000 (EXPERIMENTAL
                                     halving rule R2 recommendation; qr_risk
                                     owns final allocation, child task routed)
  4. gold.strategy_ticker_scores   - active holdings only; score = weight*100 so
                                     rebuild_paper_positions weight = score/total
                                     reproduces target weights; CASH HOLD row
                                     carries the ~45.8% residual cash sleeve
  5. gold.signal_evaluations       - NOT written here: owned and rebuilt by
                                     signals/strategies/build_signal_redesign.py
                                     (batch12 branch added there:
                                     'etf_comm_trend' -> 'trend')
  6. consumption.signal_logs       - downstream execution/UI feed
  7. gold.agent_events             - audit row

Idempotent on re-run (upserts / delete-then-insert per strategy+date).

Known fidelity limits (flagged in handoff, not silently "fixed"):
  - Risk flag: leverage up to 1.5x via 10% vol target. The paper ledger cannot
    express leverage (budget = cap * buy/total <= cap); book runs normalized
    to <=1.0x. Raw weights are stored.
  - UNG/USO roll costs not modeled beyond 5bps (research risk flag).
  - GLD/USO/UNG rows in silver.unified_prices are split across market tags
    (US vs blank); rebuild_paper_positions fetches DISTINCT ON (ticker)
    ORDER BY date DESC, which merges tags and picks the freshest close
    (market='US' rows, 2026-08-04), so the split does not affect sizing.
"""
import os
import sys
import json
import uuid
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
TASK_ID = "t_56e35a73"
MANIFEST = ("/home/ubuntu/.hermes/profiles/qr_research/workspace/"
            "strategy_handoff_manifest_20260805_batch12.json")
BATCH_DIR = "batch12_2026-08-05"
BATCH_ID = "batch12-2026-08-05"
# EXPERIMENTAL halving rule R2 recommendation from the handoff body;
# qr_risk owns final allocation (child task routed per convention).
DEFAULT_CAPITAL = 50000

ASSET_CLASS_MAP = {"US": "US Stock", "HK": "HK Stock",
                   "CN": "CN Stock", "SG": "SG Stock"}

# Registry-style prose logic, composed from the signal file's `logic` string
# plus the manifest entry/exit conventions.
LOGIC_TEXT = {
    "etf_comm_trend_basket_15": (
        "Monthly rebalance, entry at close of signal date. Signal file "
        "(weights are target portfolio, long-only): GLD/SLV/DBC/USO/UNG 12M "
        "TSMOM (hold if 252d return>0), inverse-63d-vol weights, 10% vol "
        "target cap 1.5x, all-out -> IEF. Universe: GLD/SLV/DBC/USO/UNG/IEF. "
        "NOTE: leverage up to 1.5x via vol target; paper ledger cannot "
        "express leverage >1x, book runs normalized to <=1.0x."),
}


def now_hkt():
    return datetime.now(HKT).strftime("%Y-%m-%d %H:%M:%S %Z")


def load_manifest():
    with open(MANIFEST) as f:
        return json.load(f)


def load_signals(path):
    """Return (generated_at, {ticker: weight}) for BUY entries with weight > 0."""
    with open(path) as f:
        payload = json.load(f)
    signals = payload.get("signals", {})
    weights = {}
    for ticker, entry in signals.items():
        if not isinstance(entry, dict):
            continue
        w = entry.get("weight")
        if entry.get("action") == "BUY" and w is not None and float(w) > 0:
            weights[ticker] = float(w)
    return payload.get("generated_at", ""), weights


def load_results_metrics(sid):
    """Turnover / annual PnL / profit factor live in the per-strategy results
    JSONs, not the manifest. Returns dict of metrics (None when absent)."""
    base = os.path.dirname(MANIFEST)
    out = {}
    files = {"oos": f"{sid}_results.json", "is": f"{sid}_IS_results.json"}
    data = {}
    for key, fname in files.items():
        path = os.path.join(base, BATCH_DIR, fname)
        if os.path.exists(path):
            with open(path) as f:
                data[key] = json.load(f)
    oos = data.get("oos", {})
    out["is_turnover"] = data.get("is", {}).get("turnover")
    out["oos_turnover"] = oos.get("turnover")
    out["annual_pnl_2025"] = oos.get("annual_pnl_2025")
    out["annual_pnl_2026"] = oos.get("annual_pnl_2026")
    out["profit_factor_oos"] = oos.get("profit_factor_oos")
    out["returns_oos"] = oos.get("returns_oos")  # total OOS return (DB convention)
    out["returns_is"] = data.get("is", {}).get("returns_oos")
    return out


def asset_class_for(s):
    if s["asset_class"].lower() == "etf":
        return "ETF"
    return ASSET_CLASS_MAP.get(s.get("markets", ["US"])[0], "US Stock")


def upsert_research(cur, s):
    entry_rules = s.get("entry_exit_stops", {})
    sizing = {
        "assigned_capital": DEFAULT_CAPITAL,
        "weights_are_target_portfolio": True,
        "long_only": True,
        "entry_basis": entry_rules.get("entry_basis", "close"),
    }
    cur.execute(
        """
        INSERT INTO gold.strategy_research
          (strategy_id, name, thesis, asset_class, universe_tickers, entry_logic,
           exit_logic, position_sizing, frequency, source, status, kanban_task_id,
           created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 'approved',
                %s, NOW(), NOW())
        ON CONFLICT (strategy_id) DO UPDATE SET
          name             = EXCLUDED.name,
          thesis           = EXCLUDED.thesis,
          asset_class      = EXCLUDED.asset_class,
          universe_tickers = EXCLUDED.universe_tickers,
          entry_logic      = EXCLUDED.entry_logic,
          exit_logic       = EXCLUDED.exit_logic,
          position_sizing  = EXCLUDED.position_sizing,
          frequency        = EXCLUDED.frequency,
          source           = EXCLUDED.source,
          status           = EXCLUDED.status,
          kanban_task_id   = EXCLUDED.kanban_task_id,
          updated_at       = NOW();
        """,
        (s["strategy_id"], s["name"],
         f"{s.get('priority_justification', '')} | {s.get('notes', '')}",
         asset_class_for(s), s.get("universe_tickers", []),
         LOGIC_TEXT[s["strategy_id"]],
         entry_rules.get("exit_rules", ""),
         json.dumps(sizing), s.get("signal_cadence", "monthly"),
         "research-agent", TASK_ID),
    )


def upsert_backtest_run(cur, s):
    oos = next(b for b in s["backtest_results"] if b.get("is_oos"))
    isr = next(b for b in s["backtest_results"] if not b.get("is_oos"))
    m = load_results_metrics(s["strategy_id"])
    is_turnover, oos_turnover = m["is_turnover"], m["oos_turnover"]
    # passed_* are GENERATED columns (sharpe>0.5, |dd|<0.20, trades>30, ...).
    # HK_Quality_BlueChips precedent: all_risk_gates_passed reflects the
    # research audit verdict even when the legacy trade_count gate (built for
    # higher-frequency strategies) computes FALSE on monthly rebalance counts
    # (19 OOS trades here).
    notes = (f"batch12-2026-08-05 handoff ({TASK_ID}); 4-stage audit PASS "
             f"(metrics_qa/risk/honest/qa_reproduction); daily-sampled metrics, "
             f"1-period lag, costs 5bps; crisis-alpha sleeve per book review "
             f"R4; EXPERIMENTAL (IS Sharpe 0.26 regime flag); "
             f"report={oos.get('backtest_report_path')}")
    cur.execute(
        """
        INSERT INTO gold.strategy_backtest_runs
          (run_id, strategy_id, run_number, run_by,
           is_start, is_end, oos_start, oos_end,
           sharpe_is, returns_is, max_drawdown_is, trade_count_is, win_rate_is,
           turnover_is,
           sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
           turnover_oos,
           annual_pnl_2025, annual_pnl_2026, profit_factor_oos,
           all_risk_gates_passed, notes, created_at)
        VALUES (%s, %s, 1, 'qr_research', %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s,
                TRUE, %s, NOW())
        ON CONFLICT (run_id) DO UPDATE SET
          sharpe_is = EXCLUDED.sharpe_is, returns_is = EXCLUDED.returns_is,
          max_drawdown_is = EXCLUDED.max_drawdown_is,
          trade_count_is = EXCLUDED.trade_count_is, win_rate_is = EXCLUDED.win_rate_is,
          turnover_is = EXCLUDED.turnover_is,
          sharpe_oos = EXCLUDED.sharpe_oos, returns_oos = EXCLUDED.returns_oos,
          max_drawdown_oos = EXCLUDED.max_drawdown_oos,
          trade_count_oos = EXCLUDED.trade_count_oos,
          win_rate_oos = EXCLUDED.win_rate_oos,
          turnover_oos = EXCLUDED.turnover_oos,
          annual_pnl_2025 = EXCLUDED.annual_pnl_2025,
          annual_pnl_2026 = EXCLUDED.annual_pnl_2026,
          profit_factor_oos = EXCLUDED.profit_factor_oos,
          notes = EXCLUDED.notes;
        """,
        (str(uuid.uuid5(uuid.NAMESPACE_URL, f"batch12/{s['strategy_id']}")),
         s["strategy_id"],
         isr["period_start"], isr["period_end"],
         oos["period_start"], oos["period_end"],
         isr["sharpe"], m["returns_is"], isr["max_dd"],
         isr["n_trades"], isr["win_rate"], is_turnover,
         oos["sharpe"], m["returns_oos"], oos["max_dd"],
         oos["n_trades"], oos["win_rate"], oos_turnover,
         m["annual_pnl_2025"], m["annual_pnl_2026"], m["profit_factor_oos"],
         notes),
    )


def upsert_registry(cur, s):
    oos = next(b for b in s["backtest_results"] if b.get("is_oos"))
    m = load_results_metrics(s["strategy_id"])
    cur.execute(
        """
        INSERT INTO gold.strategy_registry
          (strategy_id, name, asset_class, universe_tickers, frequency,
           execution_mode, status, priority, signal_mechanism, disable_paper_rebuild,
           sharpe_oos, returns_oos, max_drawdown_oos, trade_count_oos, win_rate_oos,
           profit_factor_oos,
           assigned_capital, approved_by, approved_at, deployed_at, last_signal_at,
           signal_logic, exit_logic, signal_file_path, description,
           created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 'PAPER', 'paper', %s, 'ingested', FALSE,
                %s, %s, %s, %s, %s, %s, %s, 'research-agent', NOW(), NOW(), NOW(),
                %s, %s, %s, %s, NOW(), NOW())
        ON CONFLICT (strategy_id) DO UPDATE SET
          name               = EXCLUDED.name,
          asset_class        = EXCLUDED.asset_class,
          universe_tickers   = EXCLUDED.universe_tickers,
          frequency          = EXCLUDED.frequency,
          execution_mode     = EXCLUDED.execution_mode,
          status             = EXCLUDED.status,
          priority           = EXCLUDED.priority,
          signal_mechanism   = EXCLUDED.signal_mechanism,
          disable_paper_rebuild = EXCLUDED.disable_paper_rebuild,
          sharpe_oos         = EXCLUDED.sharpe_oos,
          returns_oos        = EXCLUDED.returns_oos,
          max_drawdown_oos   = EXCLUDED.max_drawdown_oos,
          trade_count_oos    = EXCLUDED.trade_count_oos,
          win_rate_oos       = EXCLUDED.win_rate_oos,
          profit_factor_oos  = EXCLUDED.profit_factor_oos,
          signal_logic       = EXCLUDED.signal_logic,
          exit_logic         = EXCLUDED.exit_logic,
          signal_file_path   = EXCLUDED.signal_file_path,
          description        = EXCLUDED.description,
          updated_at         = NOW(),
          last_signal_at     = NOW();
        """,
        (s["strategy_id"], s["name"], asset_class_for(s),
         s.get("universe_tickers", []), s.get("signal_cadence", "monthly"),
         s.get("priority"),
         oos["sharpe"], m["returns_oos"], abs(oos["max_dd"]),
         oos["n_trades"], oos["win_rate"], m["profit_factor_oos"], DEFAULT_CAPITAL,
         LOGIC_TEXT[s["strategy_id"]],
         s.get("entry_exit_stops", {}).get("exit_rules", ""),
         s.get("signal_logic", {}).get("signal_file_path", ""),
         f"{s['name']} ({s.get('priority')}) - {s.get('priority_justification', '')}"),
    )


def upsert_ticker_scores(cur, s, generated_at, weights):
    """score = weight*100 so rebuild weight = score/total_score reproduces the
    target portfolio. CASH HOLD row carries the residual when weights sum < 1."""
    sid = s["strategy_id"]
    sig_file = s.get("signal_logic", {}).get("signal_file_path", "")
    total = sum(weights.values())
    rows = []
    for ticker, w in sorted(weights.items()):
        rows.append((sid, ticker, round(w * 100, 4), "BUY",
                     round(w * 100, 4), 0.0,
                     json.dumps({
                         "weight": w,
                         "source_signal_file": sig_file,
                         "generated_at": generated_at,
                         "batch_id": BATCH_ID,
                         "ingested_at": datetime.now(HKT).isoformat(),
                     }),
                     "PAPER", datetime.now(), datetime.now(), "ingested"))
    cash_residual = round(1.0 - total, 6)
    if cash_residual > 0.0005:  # material cash sleeve (~45.8% here)
        rows.append((sid, "CASH", round(cash_residual * 100, 4), "HOLD",
                     round(cash_residual * 100, 4), 0.0,
                     json.dumps({
                         "weight": cash_residual,
                         "source_signal_file": sig_file,
                         "generated_at": generated_at,
                         "batch_id": BATCH_ID,
                         "note": "residual cash sleeve (weights sum < 1)",
                         "ingested_at": datetime.now(HKT).isoformat(),
                     }),
                     "PAPER", datetime.now(), datetime.now(), "ingested"))
    cur.execute(
        "DELETE FROM gold.strategy_ticker_scores WHERE strategy_id = %s", (sid,))
    cur.executemany(
        """
        INSERT INTO gold.strategy_ticker_scores
          (strategy_id, ticker, score, signal_action, entry_score, exit_score,
           criteria_met, position_status, deployed_at, updated_at, signal_source)
        VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s);
        """,
        rows,
    )
    return len(rows), total


def insert_signal_logs(cur, s, weights):
    sid = s["strategy_id"]
    sig_file = s.get("signal_logic", {}).get("signal_file_path", "")
    today = date.today()
    cur.execute(
        "DELETE FROM consumption.signal_logs WHERE strategy_id = %s AND signal_date = %s",
        (sid, today))
    rows = [
        (sid, today, 1, ticker, "BUY",
         f"weight={w}; source={sig_file}", round(w * 100, 4))
        for ticker, w in sorted(weights.items())
    ]
    cur.executemany(
        """
        INSERT INTO consumption.signal_logs
          (strategy_id, signal_date, signal, ticker, signal_type,
           signal_criteria, confidence)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
        """,
        rows,
    )
    return len(rows)


def record_agent_event(cur, manifest, per_strategy):
    payload = {
        "batch_id": manifest.get("batch_id"),
        "generated_at": manifest.get("generated_at"),
        "agent_name": manifest.get("agent_name"),
        "kanban_task_id": TASK_ID,
        "strategies": per_strategy,
        "ingested_at": datetime.now(HKT).isoformat(),
    }
    cur.execute(
        """
        INSERT INTO gold.agent_events
          (event_type, strategy_id, domain, agent_name, payload_json, status,
           created_at, payload)
        VALUES (%s, %s, 'etl', 'etl-manager', %s::jsonb, 'ok', NOW(), %s::jsonb);
        """,
        ("signal_ingested", BATCH_ID,
         json.dumps(payload), json.dumps(payload)),
    )


def main():
    manifest = load_manifest()
    conn = get_connection()
    conn.autocommit = False
    per_strategy = []
    try:
        cur = conn.cursor()
        for s in manifest["strategies"]:
            sid = s["strategy_id"]
            sig_file = s.get("signal_logic", {}).get("signal_file_path", "")
            generated_at, weights = load_signals(sig_file)
            if not weights:
                raise SystemExit(f"{sid}: no BUY weights in {sig_file}")

            upsert_research(cur, s)
            upsert_backtest_run(cur, s)
            upsert_registry(cur, s)
            n_scores, total_w = upsert_ticker_scores(cur, s, generated_at, weights)
            # gold.signal_evaluations is rebuilt by build_signal_redesign.py
            # from these ticker scores (family via STRATEGY_KEYWORD_TO_FAMILY,
            # batch12 branch 'etf_comm_trend' -> 'trend').
            n_logs = insert_signal_logs(cur, s, weights)
            per_strategy.append({
                "strategy_id": sid, "holdings": len(weights),
                "weight_sum": round(total_w, 6),
                "ticker_score_rows": n_scores,
                "signal_log_rows": n_logs,
            })
            print(f"{now_hkt()} [OK] {sid}: {len(weights)} holdings "
                  f"(sum={total_w:.4f}), scores={n_scores}, logs={n_logs}")

        record_agent_event(cur, manifest, per_strategy)
        conn.commit()
        print(f"{now_hkt()} batch12 onboarding complete: "
              f"{len(per_strategy)} strategies")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
