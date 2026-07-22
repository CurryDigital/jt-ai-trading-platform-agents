#!/usr/bin/env python3
"""
audit_strategy_consistency.py — READ-ONLY consistency + completeness audit
of every strategy's signal pipeline. Zero writes.

Answers, per strategy in gold.strategy_registry:
  1. SIGNAL MECHANISM — how does this strategy get fresh signals?
       criteria     : has gold.strategy_signal_criteria rows → build_strategy_scores.py
       computed     : a dedicated recurring calculator (s9_macd, etf momentum, ETF paper runners)
       file-ingest  : signals come from a qr_research JSON via ingest_paper_signal.py
       ONBOARD-ONLY : only ever written by a dated one-off ingest script → NOT refreshing
       none         : no path found → stale forever
  2. FRESHNESS — max(updated_at) in strategy_ticker_scores vs today.
  3. BACKTEST COMPLETENESS — has a strategy_backtest_runs row? trade_count_oos,
     all_risk_gates_passed, profit_factor_oos present & real (not estimated)?
  4. PUBLISHED — is it in gold.v_pipeline_ui_feed (passes the frontend gate)?

The point is to make "which strategies generate the right data at the right
time" a table of facts, so the fix (one consistent recurring path per
mechanism) is driven by evidence, not guesswork.
"""
import os
import sys
from datetime import date, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.normpath(os.path.join(_HERE, '..'))
_ETL_SHARED = os.path.join(_REPO, 'agents', 'etl', 'shared', 'scripts')
if _ETL_SHARED not in sys.path: sys.path.insert(0, _ETL_SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# Strategies with a dedicated recurring COMPUTED generator (grep of the repo).
COMPUTED = {
    'S9_MACD_Momentum_V2': 's9_macd_daily.py',
    'ETF_US_Sector_Relative_Momentum': 'calc_etf_relative_momentum.py',
    'ETF_Multi_Asset_Tactical_Allocation': 'paper_run_etf_multi_asset.py',
    'ETF_Covered_Call_Income_Rotation': 'paper_run_etf_covered_call.py',
}


def _days_stale(ts):
    if ts is None:
        return None
    d = ts.date() if isinstance(ts, datetime) else ts
    return (date.today() - d).days


def main() -> int:
    conn = get_connection()
    cur = conn.cursor()

    # Registry universe.
    cur.execute("""
        SELECT strategy_id, name, status, execution_mode, priority,
               COALESCE(array_length(universe_tickers, 1), 0) AS n_univ,
               last_signal_at
        FROM gold.strategy_registry
        WHERE retired_at IS NULL
        ORDER BY strategy_id
    """)
    reg = {r[0]: r for r in cur.fetchall()}

    # Which have criteria rows.
    cur.execute("SELECT DISTINCT strategy_id FROM gold.strategy_signal_criteria")
    has_criteria = {r[0] for r in cur.fetchall()}

    # Latest ticker-score freshness + count per strategy.
    cur.execute("""
        SELECT strategy_id, COUNT(*), MAX(updated_at)
        FROM gold.strategy_ticker_scores GROUP BY strategy_id
    """)
    scores = {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    # Backtest completeness (latest run per strategy).
    cur.execute("""
        SELECT DISTINCT ON (strategy_id) strategy_id, trade_count_oos,
               sharpe_oos, all_risk_gates_passed, profit_factor_oos, notes
        FROM gold.strategy_backtest_runs
        ORDER BY strategy_id, created_at DESC
    """)
    bt = {r[0]: r for r in cur.fetchall()}

    # Published set.
    published = set()
    cur.execute("SELECT to_regclass('gold.v_pipeline_ui_feed')")
    if cur.fetchone()[0] is not None:
        cur.execute("SELECT id FROM gold.v_pipeline_ui_feed")
        published = {r[0] for r in cur.fetchall()}

    # Signal-history depth (migration 005/008).
    hist = {}
    cur.execute("SELECT to_regclass('gold.strategy_ticker_scores_history')")
    if cur.fetchone()[0] is not None:
        cur.execute("""
            SELECT strategy_id, COUNT(DISTINCT snapshot_date)
            FROM gold.strategy_ticker_scores_history GROUP BY strategy_id
        """)
        hist = {r[0]: r[1] for r in cur.fetchall()}

    def mechanism(sid):
        if sid in COMPUTED:
            return f"computed ({COMPUTED[sid]})"
        if sid in has_criteria:
            return "criteria"
        if sid in scores:
            # Has scores but no computed/criteria path → onboarded by a
            # one-off ingest and not recurring.
            return "ONBOARD-ONLY"
        return "NONE"

    rows = []
    for sid, r in reg.items():
        n_scores, fresh = scores.get(sid, (0, None))
        stale = _days_stale(fresh)
        b = bt.get(sid)
        pf_estimated = bool(b and b[5] and 'estimated_return_drawdown' in (b[5] or ''))
        rows.append({
            'sid': sid, 'status': r[2], 'mode': r[3], 'priority': r[4],
            'n_univ': r[5], 'mech': mechanism(sid),
            'n_scores': n_scores, 'stale': stale,
            'bt': bool(b), 'n_oos': (b[1] if b else None),
            'gates': (b[3] if b else None),
            'pf': (b[4] if b else None), 'pf_estimated': pf_estimated,
            'pub': sid in published, 'hist_days': hist.get(sid, 0),
        })

    print("=" * 110)
    print(f"STRATEGY CONSISTENCY AUDIT — {len(rows)} active registry strategies — {date.today()}")
    print("=" * 110)
    hdr = (f"{'strategy_id':<38} {'mechanism':<28} {'univ':>4} {'scores':>6} "
           f"{'stale':>6} {'oos':>4} {'gates':>5} {'pf':>6} {'pub':>3} {'hist':>4}")
    print(hdr)
    print("-" * 110)
    for x in sorted(rows, key=lambda z: (z['mech'], z['sid'])):
        pf = 'EST' if x['pf_estimated'] else ('—' if x['pf'] is None else f"{float(x['pf']):.2f}")
        print(f"{x['sid']:<38} {x['mech']:<28} {x['n_univ']:>4} {x['n_scores']:>6} "
              f"{('—' if x['stale'] is None else str(x['stale'])+'d'):>6} "
              f"{('—' if x['n_oos'] is None else x['n_oos']):>4} "
              f"{('—' if x['gates'] is None else ('Y' if x['gates'] else 'N')):>5} "
              f"{pf:>6} {('Y' if x['pub'] else '·'):>3} {x['hist_days']:>4}")

    # ── Problem rollups ──────────────────────────────────────────────────
    def flag(pred):
        return sorted(x['sid'] for x in rows if pred(x))

    print("\n" + "=" * 110)
    print("PROBLEM ROLLUPS")
    print("=" * 110)
    onboard_only = flag(lambda x: x['mech'] == 'ONBOARD-ONLY')
    no_path      = flag(lambda x: x['mech'] == 'NONE')
    stale7       = flag(lambda x: x['stale'] is not None and x['stale'] > 7)
    no_scores    = flag(lambda x: x['n_scores'] == 0)
    no_bt        = flag(lambda x: not x['bt'])
    thin_bt      = flag(lambda x: x['n_oos'] is not None and x['n_oos'] < 30)
    est_pf       = flag(lambda x: x['pf_estimated'])
    pub_thin     = flag(lambda x: x['pub'] and x['n_oos'] is not None and x['n_oos'] < 30)

    print(f"\n[SIGNAL FRESHNESS]")
    print(f"  ONBOARD-ONLY (no recurring generator — frozen at onboarding): {len(onboard_only)}")
    for s in onboard_only: print(f"      {s}")
    print(f"  NO signal path at all: {no_path or '(none)'}")
    print(f"  scores stale >7d: {stale7 or '(none)'}")
    print(f"  zero ticker scores: {no_scores or '(none)'}")

    print(f"\n[BACKTEST COMPLETENESS]")
    print(f"  no backtest_runs row: {no_bt or '(none)'}")
    print(f"  thin OOS (<30 trades, gate is 30): {thin_bt or '(none)'}")
    print(f"  ESTIMATED (fabricated) profit factor still present: {est_pf or '(none)'}")

    print(f"\n[PUBLICATION INTEGRITY]")
    print(f"  PUBLISHED but thin OOS (<30) — shouldn't pass the gate: {pub_thin or '(none)'}")

    print("\nLegend: mechanism=how signals refresh; stale=days since last score;")
    print("  oos=trade_count_oos; gates=all_risk_gates_passed; pf EST=heuristic (not measured);")
    print("  pub=in v_pipeline_ui_feed; hist=distinct snapshot days available.")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
