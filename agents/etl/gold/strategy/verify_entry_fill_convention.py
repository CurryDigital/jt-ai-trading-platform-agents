#!/usr/bin/env python3
"""Verify the declared paper-ledger entry fill convention (t_716fe5a7).

READ-ONLY. Independently re-derives every check (never imports
rebuild_paper_positions.py). Exit 0 = all checks pass, 1 = any failure.

Checks:
 1. Each of the nine reinstated books has registry entry_fill_convention
    populated with a declarable value (NEXT_OPEN|T1_CLOSE; SIGNAL_CLOSE is
    rejected by chk_entry_fill_convention).
 2. No strategy_configs fill_convention row conflicts with a registry
    declaration (override honoured only when no declaration exists).
 3. Every entry created AFTER the declaration date for the nine books
    carries entry_price_basis IN (NEXT_OPEN, NEXT_OPEN_CLOSE_FALLBACK) —
    i.e. future fills follow the declared convention and stamp the basis.
 4. Report (non-failing): remaining NULL entry_price_basis rows ledger-wide
    (historical, left as-is per operator decision 2026-11-02).
"""
import sys, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path:
    sys.path.insert(0, _ETL_SHARED)

from db import get_connection

NINE = ('us_stk_sue_mom_01_v2', 'ETF_Multi_Asset_Tactical_Allocation',
        'us_stk_lowbeta_14', 'cn_stk_lowvol_12', 'etf_vix_scaled_11',
        'ETF_US_Sector_Relative_Momentum', 'etf_def_sector_rot_12_w',
        'COMM_Gold_Trend_VolTarget', 'COMM_Copper_Trend_VolTarget')
DECLARATION_TS = '2026-11-02'
DECLARABLE = ('NEXT_OPEN', 'T1_CLOSE')
DECLARED_ENTRY_BASES = ('NEXT_OPEN', 'NEXT_OPEN_CLOSE_FALLBACK')

failures = []


def check(name, ok, detail=''):
    print(f"[{'PASS' if ok else 'FAIL'}] {detail}")
    if not ok:
        failures.append(name)


def main():
    conn = get_connection()
    cur = conn.cursor()

    # 1. declaration populated and declarable
    cur.execute("""
        SELECT strategy_id, entry_fill_convention
        FROM gold.strategy_registry
        WHERE strategy_id = ANY(%s);
    """, (list(NINE),))
    decl = dict(cur.fetchall())
    missing = [s for s in NINE if decl.get(s) not in DECLARABLE]
    check('declaration', not missing,
          f"1. nine books declared entry_fill_convention: "
          f"{len(decl) - len(missing)}/9 declarable; missing/invalid: {missing or 'none'}")

    # 2. no config/declaration conflict
    cur.execute("""
        SELECT c.strategy_id, c.config_value, r.entry_fill_convention
        FROM gold.strategy_configs c
        JOIN gold.strategy_registry r USING (strategy_id)
        WHERE c.config_key = 'fill_convention'
          AND r.entry_fill_convention IS NOT NULL
          AND upper(trim(both '"' from c.config_value::text))
              <> r.entry_fill_convention;
    """)
    conflicts = cur.fetchall()
    check('conflict', not conflicts,
          f"2. config/declaration conflicts: {conflicts or 'none'}")

    # 3. post-declaration entries follow the declared convention
    cur.execute("""
        SELECT strategy_id, ticker, entry_date, entry_price_basis
        FROM gold.paper_trades_synthetic
        WHERE strategy_id = ANY(%s)
          AND created_at >= %s
          AND (entry_price_basis IS NULL
               OR entry_price_basis NOT IN ('NEXT_OPEN', 'NEXT_OPEN_CLOSE_FALLBACK'));
    """, (list(NINE), DECLARATION_TS))
    bad = cur.fetchall()
    check('post-declaration basis', not bad,
          f"3. post-{DECLARATION_TS} entries for the nine off-convention/unstamped: "
          f"{bad or 'none'}")

    # 4. report remaining NULL basis (historical, expected non-zero)
    cur.execute("""
        SELECT strategy_id, count(*)
        FROM gold.paper_trades_synthetic
        WHERE entry_price_basis IS NULL
        GROUP BY 1 ORDER BY 1;
    """)
    nulls = cur.fetchall()
    print(f"[INFO] 4. historical NULL entry_price_basis rows (left as-is, "
          f"operator decision 2026-11-02): {nulls or 'none'}")
    print("[INFO]    label-only backfill prepared: "
          "gold/strategy/label_null_entry_basis_2026-11-02.py "
          "(dry-run default; --apply requires operator sign-off)")

    print(f"\n{'PASS' if not failures else 'FAIL'}: {len(failures)} failing checks")
    return 0 if not failures else 1


if __name__ == '__main__':
    sys.exit(main())
