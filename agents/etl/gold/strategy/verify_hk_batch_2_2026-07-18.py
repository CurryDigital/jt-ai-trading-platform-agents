#!/usr/bin/env python3
"""
Verify HK strategy batch 2 ingestion.

Checks:
- gold.strategy_registry rows for ETF_HK_Balanced_Trend and HK_Quality_BlueChips
- gold.strategy_ticker_scores counts
- gold.signal_evaluations counts
- /api/strategies/researcher returns both with correct asset_class
- broker mapping presence for HK tickers
"""
import json
import os
import sys

import requests

sys.path.insert(
    0, os.path.expanduser(
        "~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts"
    )
)
os.environ.setdefault("AWS_REGION", "ap-southeast-1")
from db import get_connection  # noqa: E402

STRATEGIES = {
    "ETF_HK_Balanced_Trend": {
        "asset_class": "ETF",
        "expected_universe": 6,
        "expected_signals": 6,
    },
    "HK_Quality_BlueChips": {
        "asset_class": "HK Stock",
        "expected_universe": 20,
        "expected_signals": 20,
    },
}

UNIVERSES = {
    "ETF_HK_Balanced_Trend": ["2800.HK", "0001.HK", "0700.HK", "1299.HK", "2318.HK", "AGG"],
    "HK_Quality_BlueChips": [
        "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK", "0011.HK",
        "0016.HK", "0027.HK", "0388.HK", "0669.HK", "0836.HK", "0939.HK",
        "0941.HK", "1038.HK", "1299.HK", "1398.HK", "1928.HK", "2318.HK",
        "2388.HK", "2628.HK",
    ],
    "HK_LowVol_Weekly": [
        "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK", "0012.HK", "0016.HK", "0017.HK",
        "0023.HK", "0027.HK", "0066.HK", "0069.HK", "0083.HK", "0088.HK", "0101.HK", "0123.HK",
        "0144.HK", "0151.HK", "0168.HK", "0197.HK", "0228.HK", "0257.HK", "0267.HK", "0270.HK",
        "0316.HK", "0388.HK", "0506.HK", "0636.HK", "0688.HK", "0700.HK", "0762.HK", "0788.HK",
        "0823.HK", "0836.HK", "0838.HK", "0883.HK", "0939.HK", "0941.HK", "0978.HK", "0998.HK",
        "1024.HK", "1038.HK", "1044.HK", "1109.HK", "1113.HK", "1211.HK", "1234.HK", "1299.HK",
        "1359.HK", "1398.HK", "1658.HK", "1810.HK", "1876.HK", "1928.HK", "1929.HK", "2015.HK",
        "2020.HK", "2269.HK", "2313.HK", "2318.HK", "2319.HK", "2331.HK", "2382.HK", "2388.HK",
        "2628.HK", "2688.HK", "2800.HK", "2899.HK", "3323.HK", "3328.HK", "3690.HK", "3868.HK",
        "3968.HK", "3988.HK", "6098.HK", "6190.HK", "6862.HK", "9616.HK", "9618.HK", "9633.HK",
        "9868.HK", "9888.HK", "9988.HK", "9992.HK", "9999.HK",
    ],
    "HK_LowVol_TrendFilter_Weekly": [
        "0001.HK", "0002.HK", "0003.HK", "0005.HK", "0006.HK", "0012.HK", "0016.HK", "0017.HK",
        "0023.HK", "0027.HK", "0066.HK", "0069.HK", "0083.HK", "0088.HK", "0101.HK", "0123.HK",
        "0144.HK", "0151.HK", "0168.HK", "0197.HK", "0228.HK", "0257.HK", "0267.HK", "0270.HK",
        "0316.HK", "0388.HK", "0506.HK", "0636.HK", "0688.HK", "0700.HK", "0762.HK", "0788.HK",
        "0823.HK", "0836.HK", "0838.HK", "0883.HK", "0939.HK", "0941.HK", "0978.HK", "0998.HK",
        "1024.HK", "1038.HK", "1044.HK", "1109.HK", "1113.HK", "1211.HK", "1234.HK", "1299.HK",
        "1359.HK", "1398.HK", "1658.HK", "1810.HK", "1876.HK", "1928.HK", "1929.HK", "2015.HK",
        "2020.HK", "2269.HK", "2313.HK", "2318.HK", "2319.HK", "2331.HK", "2382.HK", "2388.HK",
        "2628.HK", "2688.HK", "2800.HK", "2899.HK", "3323.HK", "3328.HK", "3690.HK", "3868.HK",
        "3968.HK", "3988.HK", "6098.HK", "6190.HK", "6862.HK", "9616.HK", "9618.HK", "9633.HK",
        "9868.HK", "9888.HK", "9988.HK", "9992.HK", "9999.HK",
    ],
}
all_tickers = sorted(set(t for u in UNIVERSES.values() for t in u))

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")


def verify_db():
    conn = get_connection()
    try:
        cur = conn.cursor()
        print("--- gold.strategy_registry ---")
        cur.execute(
            """
            SELECT strategy_id, name, asset_class, execution_mode, status, priority,
                   universe_tickers, sharpe_oos, max_drawdown_oos, trade_count_oos,
                   win_rate_oos, returns_oos, signal_file_path
            FROM gold.strategy_registry
            WHERE strategy_id IN %s
            ORDER BY strategy_id;
            """,
            (tuple(STRATEGIES.keys()),),
        )
        rows = cur.fetchall()
        for r in rows:
            sid = r[0]
            expected = STRATEGIES[sid]
            asset_class = r[2]
            status = r[5]
            universe = r[6]
            print(f"strategy_id={sid}")
            print(f"  name={r[1]} asset_class={asset_class} execution_mode={r[3]} status={r[4]} priority={status}")
            print(f"  universe_tickers={universe}")
            print(f"  sharpe_oos={r[7]} max_drawdown_oos={r[8]} trade_count_oos={r[9]} win_rate_oos={r[10]} returns_oos={r[11]}")
            print(f"  signal_file_path={r[12]}")
            assert asset_class == expected["asset_class"], f"asset_class mismatch for {sid}: {asset_class} != {expected['asset_class']}"
        assert len(rows) == 2, f"expected 2 registry rows, got {len(rows)}"

        print("\n--- gold.strategy_ticker_scores ---")
        cur.execute(
            """
            SELECT strategy_id, COUNT(*)
            FROM gold.strategy_ticker_scores
            WHERE strategy_id IN %s
            GROUP BY strategy_id
            ORDER BY strategy_id;
            """,
            (tuple(STRATEGIES.keys()),),
        )
        for r in cur.fetchall():
            sid, cnt = r
            expected = STRATEGIES[sid]["expected_signals"]
            print(f"{sid}: {cnt} ticker scores (expected {expected})")
            assert cnt == expected, f"ticker score count mismatch for {sid}: {cnt} != {expected}"

        print("\n--- gold.signal_evaluations ---")
        cur.execute(
            """
            SELECT family_key, COUNT(DISTINCT ticker)
            FROM gold.signal_evaluations
            WHERE family_key = 'hk_paper_v1'
            GROUP BY family_key;
            """
        )
        r = cur.fetchone()
        total = r[1] if r else 0
        expected_total = len(all_tickers)
        print(f"family_key=hk_paper_v1: {total} distinct tickers (expected {expected_total})")
        assert total == expected_total, f"signal_evaluations total mismatch: {total} != {expected_total}"

        print("\n--- gold.strategy_registry universe size ---")
        cur.execute(
            """
            SELECT strategy_id, array_length(universe_tickers, 1)
            FROM gold.strategy_registry
            WHERE strategy_id IN %s
            ORDER BY strategy_id;
            """,
            (tuple(STRATEGIES.keys()),),
        )
        for r in cur.fetchall():
            sid, n = r
            expected = STRATEGIES[sid]["expected_universe"]
            print(f"{sid}: universe_tickers has {n} tickers (expected {expected})")
            assert n == expected, f"universe size mismatch for {sid}: {n} != {expected}"

        print("\n--- broker mapping check (bronze.ibkr_contracts) ---")
        cur.execute(
            """
            SELECT symbol, con_id, exchange, currency, local_symbol
            FROM bronze.ibkr_contracts
            WHERE symbol = ANY(%s)
            ORDER BY symbol;
            """,
            (all_tickers,),
        )
        found = {r[0]: r[1] for r in cur.fetchall()}
        missing = [t for t in all_tickers if t not in found]
        print(f"  mapped: {len(found)} / {len(all_tickers)}")
        if missing:
            print(f"  WARNING: missing broker contracts for {missing}")
        else:
            print("  all tickers mapped")
        return True
    finally:
        conn.close()


def verify_api():
    url = f"{API_BASE}/api/strategies/researcher"
    print(f"\n--- GET {url} ---")
    resp = requests.get(url, timeout=30)
    print(f"status={resp.status_code}")
    resp.raise_for_status()
    data = resp.json()
    strategies = data.get("strategies", []) if isinstance(data, dict) else data
    by_id = {s.get("id"): s for s in strategies}
    for sid, expected in STRATEGIES.items():
        assert sid in by_id, f"{sid} not in /api/strategies/researcher"
        s = by_id[sid]
        ac = s.get("asset_class")
        print(f"{sid}: asset_class={ac}")
        assert ac == expected["asset_class"], f"API asset_class mismatch for {sid}: {ac} != {expected['asset_class']}"
    return True


if __name__ == "__main__":
    try:
        verify_db()
        verify_api()
        print("\n✅ All verification checks passed.")
    except Exception as e:
        print(f"\n❌ Verification failed: {e}")
        sys.exit(1)
