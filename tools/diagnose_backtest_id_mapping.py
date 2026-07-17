#!/usr/bin/env python3
"""
diagnose_backtest_id_mapping.py — READ-ONLY evidence gatherer for the
migration-006 backfill (gold.strategy_backtests.registry_strategy_id).

Context: gold.strategy_backtests keys on SMALLINT ids (found live: 1, 2, 3),
gold.strategy_registry keys on semantic varchar ids. Migration 006 added the
bridge column; the mapping must be confirmed from evidence, not guessed.

Working hypothesis this script tests: smallint ids are the SIGNAL-AGENT
numeric id space (agents/signals/strategies/registry.json: 1 = Dual EMA
crossover, 2 = 52-week high momentum, 3 = RSI(2) mean reversion), which has
no overlap with the 34 semantic registry ids — in which case the honest
backfill is NO mapping (leave registry_strategy_id NULL and stop expecting
these rows to feed the registry).

Evidence collected (all SELECTs, zero writes):
  A. Full gold.strategy_backtests rows.
  B. Name resolution via gold.strategy_signals (same smallint id space AND
     a strategy_name column — written by the signal agent's save()).
  C. The repo's registry.json entry (or retired-id status) for each id.
  D. Metric cross-match: does any semantic strategy in
     gold.strategy_backtest_runs (OOS) or gold.strategy_registry (*_oos)
     carry the same sharpe/win_rate/max_dd/n_trades? Exact-ish matches are
     printed as CANDIDATES only — never auto-applied.

Output ends with a verdict per numeric id. This script never UPDATEs.
"""
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, '..'))
_ETL_SHARED = os.path.join(_REPO, 'agents', 'etl', 'shared', 'scripts')
if _ETL_SHARED not in sys.path: sys.path.insert(0, _ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')

from db import get_connection

REGISTRY_JSON = os.path.join(_REPO, 'agents', 'signals', 'strategies', 'registry.json')


def _table_exists(cur, qualified: str) -> bool:
    cur.execute("SELECT to_regclass(%s)", (qualified,))
    return cur.fetchone()[0] is not None


def _fmt(v):
    return "NULL" if v is None else v


def main() -> int:
    conn = get_connection()
    cur = conn.cursor()

    print("=" * 72)
    print("A. gold.strategy_backtests — full contents")
    print("=" * 72)
    cur.execute("""
        SELECT strategy_id, run_date, sharpe, calmar, max_dd, win_rate,
               n_trades, period_start, period_end,
               registry_strategy_id
        FROM gold.strategy_backtests
        ORDER BY strategy_id, run_date
    """)
    backtests = cur.fetchall()
    numeric_ids = sorted({r[0] for r in backtests})
    for r in backtests:
        print(f"  id={r[0]}  run={r[1]}  sharpe={_fmt(r[2])}  calmar={_fmt(r[3])}  "
              f"max_dd={_fmt(r[4])}  win_rate={_fmt(r[5])}  n_trades={_fmt(r[6])}  "
              f"period={r[7]}..{r[8]}  registry_strategy_id={_fmt(r[9])}")
    if not backtests:
        print("  (empty — nothing to map)")
        conn.close()
        return 0

    print()
    print("=" * 72)
    print("B. Name resolution via gold.strategy_signals (same smallint id space)")
    print("=" * 72)
    signal_names = {}
    if _table_exists(cur, 'gold.strategy_signals'):
        cur.execute("""
            SELECT strategy_id, strategy_name,
                   COUNT(*) AS n_rows, MIN(date), MAX(date)
            FROM gold.strategy_signals
            WHERE strategy_id = ANY(%s)
            GROUP BY strategy_id, strategy_name
            ORDER BY strategy_id
        """, (numeric_ids,))
        rows = cur.fetchall()
        for sid, name, n, dmin, dmax in rows:
            signal_names.setdefault(sid, []).append(name)
            print(f"  id={sid}  strategy_name={name!r}  ({n} signal rows, {dmin}..{dmax})")
        if not rows:
            print("  (no gold.strategy_signals rows for these ids)")
    else:
        print("  gold.strategy_signals does not exist")

    print()
    print("=" * 72)
    print("C. Repo registry.json identity for these numeric ids")
    print("=" * 72)
    try:
        with open(REGISTRY_JSON) as f:
            reg = json.load(f)
        by_id = {e['id']: e for e in reg.get('strategies', [])}
        retired = set(reg.get('retired_ids', []))
        for sid in numeric_ids:
            if sid in by_id:
                e = by_id[sid]
                print(f"  id={sid}: ACTIVE signal-agent strategy {e['name']!r} "
                      f"(tier={e.get('tier')}, enabled={e.get('enabled')})")
            elif sid in retired:
                print(f"  id={sid}: RETIRED signal-agent id (deleted stub)")
            else:
                print(f"  id={sid}: not present in registry.json at all")
    except Exception as e:
        print(f"  (could not read {REGISTRY_JSON}: {e})")

    print()
    print("=" * 72)
    print("D. Metric cross-match against semantic-keyed backtest data")
    print("=" * 72)
    candidates = {}
    if _table_exists(cur, 'gold.strategy_backtest_runs'):
        for r in backtests:
            sid, _, sharpe, _, max_dd, win_rate, n_trades = r[0], r[1], r[2], r[3], r[4], r[5], r[6]
            cur.execute("""
                SELECT strategy_id, run_number, sharpe_oos, max_drawdown_oos,
                       win_rate_oos, trade_count_oos
                FROM gold.strategy_backtest_runs
                WHERE (sharpe_oos IS NOT NULL AND %s IS NOT NULL
                       AND ABS(sharpe_oos - %s::numeric) < 0.005)
                   OR (trade_count_oos IS NOT NULL AND trade_count_oos = %s)
                ORDER BY strategy_id, run_number
            """, (sharpe, sharpe, n_trades))
            for m in cur.fetchall():
                score = 0
                if sharpe is not None and m[2] is not None and abs(float(m[2]) - float(sharpe)) < 0.005:
                    score += 1
                if n_trades is not None and m[5] == n_trades:
                    score += 1
                if win_rate is not None and m[4] is not None and abs(float(m[4]) - float(win_rate)) < 0.005:
                    score += 1
                if score >= 2:
                    candidates.setdefault(sid, []).append((m[0], f"backtest_runs run#{m[1]}", score))
                print(f"  numeric id={sid} ~ backtest_runs[{m[0]}] run#{m[1]}: "
                      f"sharpe_oos={_fmt(m[2])} max_dd_oos={_fmt(m[3])} "
                      f"win_rate_oos={_fmt(m[4])} trades_oos={_fmt(m[5])} "
                      f"(matching fields: {score})")
    else:
        print("  gold.strategy_backtest_runs does not exist")

    cur.execute("""
        SELECT strategy_id, sharpe_oos, max_drawdown_oos, win_rate_oos, trade_count_oos
        FROM gold.strategy_registry
        WHERE sharpe_oos IS NOT NULL OR win_rate_oos IS NOT NULL
        ORDER BY strategy_id
    """)
    reg_stats = cur.fetchall()
    for r in backtests:
        sid, sharpe, max_dd, win_rate, n_trades = r[0], r[2], r[4], r[5], r[6]
        for g in reg_stats:
            score = 0
            if sharpe is not None and g[1] is not None and abs(float(g[1]) - float(sharpe)) < 0.005:
                score += 1
            if win_rate is not None and g[3] is not None and abs(float(g[3]) - float(win_rate)) < 0.005:
                score += 1
            if n_trades is not None and g[4] == n_trades:
                score += 1
            if score >= 2:
                candidates.setdefault(sid, []).append((g[0], "registry *_oos stats", score))
                print(f"  numeric id={sid} ~ registry[{g[0]}]: "
                      f"sharpe_oos={g[1]} win_rate_oos={g[3]} trades_oos={g[4]} "
                      f"(matching fields: {score})")

    if not candidates:
        print("  (no >=2-field metric matches anywhere)")

    print()
    print("=" * 72)
    print("VERDICT (per numeric id — for the operator, nothing applied)")
    print("=" * 72)
    for sid in numeric_ids:
        names = signal_names.get(sid)
        cands = candidates.get(sid, [])
        print(f"  id={sid}:")
        if names:
            print(f"    signal-agent identity: {names} (from gold.strategy_signals)")
        if cands:
            for c in sorted(cands, key=lambda x: -x[2]):
                print(f"    CANDIDATE semantic match: {c[0]} via {c[1]} ({c[2]} fields)")
            print(f"    → if a candidate is confirmed by qr_research, backfill:")
            print(f"      UPDATE gold.strategy_backtests SET registry_strategy_id = '<id>' WHERE strategy_id = {sid};")
        else:
            print(f"    no semantic candidate. If the signal-agent identity above has no")
            print(f"    gold.strategy_registry row, the honest backfill is NONE — leave")
            print(f"    registry_strategy_id NULL (these backtests belong to the signal-agent")
            print(f"    numeric space, not the registry), or first onboard that strategy to")
            print(f"    the registry and then map it.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
