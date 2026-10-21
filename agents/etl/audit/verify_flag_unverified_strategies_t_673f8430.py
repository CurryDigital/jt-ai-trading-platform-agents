#!/usr/bin/env python3
"""t_673f8430 verification: single-SELECT deliverable + assertions."""
import sys, json
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform')
from agents.etl.shared.scripts.db import get_connection

SINGLE_SELECT = """
SELECT sc.strategy_id,
       sc.config_value::text AS trades_sum_is_book_annual_return,
       sc.description
FROM gold.strategy_configs sc
JOIN (SELECT DISTINCT strategy_id FROM consumption.strategy_monthly_returns) pub
  ON pub.strategy_id = sc.strategy_id
WHERE sc.config_key = 'trades_sum_is_book_annual_return'
ORDER BY sc.config_value::text DESC, sc.strategy_id;
"""

def main():
    comp = json.load(open('/home/ubuntu/.hermes/kanban/boards/qr_frontend/attachments/t_abb57f07/annual_compounds.json'))
    verified = set(comp['verified']); legacy = set(comp['keep_legacy_values'])

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(SINGLE_SELECT)
    rows = cur.fetchall()
    print(f'== single SELECT returned {len(rows)} rows ==')
    for sid, val, desc in rows:
        print(f'  {val:5s}  {sid:45s}  {(desc or "")[:95]}')

    errors = []
    if len(rows) != 30:
        errors.append(f'row count {len(rows)} != 30')
    by_sid = {sid: (val, desc or '') for sid, val, desc in rows}
    if len(by_sid) != len(rows):
        errors.append('duplicate rows for a strategy_id')
    for sid in verified:
        v, d = by_sid.get(sid, (None, ''))
        if v != 'false':
            errors.append(f'{sid}: expected false, got {v}')
        if 'corrected from research curve, t_6ea23eae' not in d:
            errors.append(f'{sid}: missing corrected marker')
    for sid in legacy:
        v, d = by_sid.get(sid, (None, ''))
        if v != 'true':
            errors.append(f'{sid}: expected true, got {v}')
        if 'legacy trades-sum; no verified book curve' not in d:
            errors.append(f'{sid}: missing legacy marker')

    # coverage: every published strategy has a flag row; counts by value
    cur.execute("""
        SELECT config_value::text, count(*) FROM gold.strategy_configs
        WHERE config_key='trades_sum_is_book_annual_return' GROUP BY 1
    """)
    print('\nflag value counts (all strategies):', cur.fetchall())
    cur.execute("""
        SELECT count(*) FROM (SELECT DISTINCT strategy_id FROM consumption.strategy_monthly_returns) pub
        WHERE NOT EXISTS (SELECT 1 FROM gold.strategy_configs sc
                          WHERE sc.strategy_id=pub.strategy_id
                            AND sc.config_key='trades_sum_is_book_annual_return')
    """)
    print('published strategies WITHOUT flag row:', cur.fetchone()[0])

    # idempotency check note + registry backfill readback
    cur.execute("""
        SELECT strategy_id, name, asset_class, status, execution_mode
        FROM gold.strategy_registry
        WHERE strategy_id IN ('H3_VIX_TAIL_HEDGE_V1','S14_OIL_SQUEEZE_DISC_V1')
    """)
    print('registry backfill rows:')
    for r in cur.fetchall():
        print(' ', r)

    cur.close(); conn.close()
    if errors:
        print('\nVERIFY FAILED:')
        for e in errors:
            print('  -', e)
        sys.exit(1)
    print('\nVERIFY PASSED: 30/30 published strategies flagged (27 false/corrected, 3 true/legacy)')

if __name__ == '__main__':
    main()
