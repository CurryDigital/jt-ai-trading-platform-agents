#!/usr/bin/env python3
"""Verify HK LowVol batch ingestion standalone."""
import os, sys
sys.path.insert(0, os.path.expanduser("~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"))
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection

STRATEGIES = {
    "HK_LowVol_Weekly": {"asset_class": "HK Stock", "expected_universe": 87, "expected_signals": 5},
    "HK_LowVol_TrendFilter_Weekly": {"asset_class": "HK Stock", "expected_universe": 87, "expected_signals": 5},
}
TARGET_TICKERS = ["0002.HK", "0003.HK", "0636.HK", "0941.HK", "1234.HK"]

def verify_db():
    conn = get_connection()
    try:
        cur = conn.cursor()
        print("--- gold.strategy_research ---")
        cur.execute("SELECT strategy_id, name, asset_class, status, universe_tickers FROM gold.strategy_research WHERE strategy_id IN %s ORDER BY strategy_id;", (tuple(STRATEGIES.keys()),))
        rows = cur.fetchall()
        assert len(rows) == 2, f"expected 2 research rows, got {len(rows)}"
        for r in rows:
            sid = r[0]
            print(f"{sid}: status={r[3]} asset_class={r[2]} universe={len(r[4])} tickers")
            assert r[3] == "approved"
            assert r[2] == STRATEGIES[sid]["asset_class"]

        print("\n--- gold.strategy_backtest_runs ---")
        cur.execute("SELECT strategy_id, run_number, oos_start, oos_end, sharpe_oos, max_drawdown_oos, trade_count_oos, win_rate_oos, returns_oos, all_risk_gates_passed FROM gold.strategy_backtest_runs WHERE strategy_id IN %s ORDER BY strategy_id, run_number DESC;", (tuple(STRATEGIES.keys()),))
        for r in cur.fetchall():
            print(f"{r[0]}: run={r[1]} oos={r[2]}..{r[3]} sharpe={r[4]} maxdd={r[5]} trades={r[6]} win={r[7]} ret={r[8]} gates={r[9]}")
            assert r[4] is not None and r[6] is not None

        print("\n--- gold.strategy_registry ---")
        cur.execute("SELECT strategy_id, name, asset_class, execution_mode, status, priority, universe_tickers, sharpe_oos, max_drawdown_oos, trade_count_oos, win_rate_oos, returns_oos, signal_file_path FROM gold.strategy_registry WHERE strategy_id IN %s ORDER BY strategy_id;", (tuple(STRATEGIES.keys()),))
        for r in cur.fetchall():
            sid = r[0]
            print(f"{sid}: asset_class={r[2]} execution_mode={r[3]} status={r[4]} priority={r[5]} universe={len(r[6])}")
            print(f"  sharpe={r[7]} maxdd={r[8]} trades={r[9]} win={r[10]} ret={r[11]}")
            print(f"  signal_file={r[12]}")
            assert r[2] == STRATEGIES[sid]["asset_class"]
            assert len(r[6]) == STRATEGIES[sid]["expected_universe"]

        print("\n--- gold.strategy_ticker_scores ---")
        cur.execute("SELECT strategy_id, COUNT(*) FROM gold.strategy_ticker_scores WHERE strategy_id IN %s GROUP BY strategy_id ORDER BY strategy_id;", (tuple(STRATEGIES.keys()),))
        for r in cur.fetchall():
            sid, cnt = r
            print(f"{sid}: {cnt} ticker scores (expected {STRATEGIES[sid]['expected_signals']})")
            assert cnt == STRATEGIES[sid]["expected_signals"]

        print("\n--- gold.signal_evaluations target tickers ---")
        cur.execute("SELECT family_key, COUNT(DISTINCT ticker) FROM gold.signal_evaluations WHERE family_key='hk_paper_v1' AND ticker = ANY(%s) GROUP BY family_key;", (TARGET_TICKERS,))
        r = cur.fetchone()
        total = r[1] if r else 0
        print(f"family_key=hk_paper_v1: {total} distinct target tickers (expected 5)")
        assert total == 5

        print("\n--- gold.v_pipeline_ui_feed ---")
        cur.execute("SELECT id, name, asset, stage, mode, sharpe, returns, dd, trades FROM gold.v_pipeline_ui_feed WHERE id IN %s ORDER BY id;", (tuple(STRATEGIES.keys()),))
        for r in cur.fetchall():
            print(f"{r[0]}: asset={r[2]} stage={r[3]} mode={r[4]} sharpe={r[5]} returns={r[6]} dd={r[7]} trades={r[8]}")

        print("\n--- broker mapping check (bronze.ibkr_contracts) ---")
        cur.execute("SELECT symbol, con_id, exchange, currency, local_symbol FROM bronze.ibkr_contracts WHERE symbol = ANY(%s) ORDER BY symbol;", (TARGET_TICKERS,))
        found = {r[0]: r[1] for r in cur.fetchall()}
        missing = [t for t in TARGET_TICKERS if t not in found]
        print(f"  mapped: {len(found)} / {len(TARGET_TICKERS)}")
        if missing:
            print(f"  WARNING: missing broker contracts for {missing}")
        else:
            print("  all target tickers mapped")
        return True
    finally:
        conn.close()

if __name__ == "__main__":
    try:
        verify_db()
        print("\nAll verification checks passed.")
    except Exception as e:
        print(f"\nVerification failed: {e}")
        sys.exit(1)
