#!/usr/bin/env python3
"""
t_673f8430: Flag unverified strategies in gold.strategy_configs (final apply).

Step 1: registry backfill for H3_VIX_TAIL_HEDGE_V1 and S14_OIL_SQUEEZE_DISC_V1
  (published in consumption.strategy_monthly_returns via trades-recon but had no
  gold.strategy_registry row, which FK-blocks strategy_configs inserts).
  Precedent: vix_spike_fade_entry backfill (kanban t_469a21c1), status reflects
  research outcome; both failed risk gates / auto-dropped -> status='retired',
  execution_mode='SIMULATION' so no live/paper engine picks them up.

Step 2: upsert (strategy_id, 'trades_sum_is_book_annual_return') for all 30
  published strategies:
  - 27 verified (t_abb57f07) -> false + marker 'annual_pnl_YYYY corrected from
    research curve, t_6ea23eae'
  - 3 keep-legacy -> true + marker 'annual_pnl_YYYY = legacy trades-sum; no
    verified book curve - see t_6ea23eae'

Idempotent: ON CONFLICT DO NOTHING for registry; marker appended to description
only when absent.
"""
import sys, json
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform')
from agents.etl.shared.scripts.db import get_connection
from psycopg2.extras import Json

MARKER_CORRECTED = 'annual_pnl_YYYY corrected from research curve, t_6ea23eae'
MARKER_LEGACY = 'annual_pnl_YYYY = legacy trades-sum; no verified book curve - see t_6ea23eae'
DESC_CORRECTED = 'Book annuals verified against research curve (t_abb57f07). ' + MARKER_CORRECTED
DESC_LEGACY = ('No verified research curve artifact; stored annual_pnl_YYYY are '
               'legacy values. ' + MARKER_LEGACY)

REGISTRY_BACKFILL = [
    {
        'strategy_id': 'H3_VIX_TAIL_HEDGE_V1',
        'name': 'VIX Tail Hedge (H3)',
        'asset_class': 'equity_index',
        'universe_tickers': ['^VIX'],
        'description': ('Registry backfill (kanban t_673f8430): published via trades-recon in '
                        'consumption.strategy_monthly_returns but had no registry row; FK-blocked '
                        'strategy_configs. Research outcome: all_risk_gates_passed=false (grid-search '
                        'artifact, ^VIX spot proxy not tradable). Non-deployable.'),
    },
    {
        'strategy_id': 'S14_OIL_SQUEEZE_DISC_V1',
        'name': 'Oil Squeeze Dislocation (S14)',
        'asset_class': 'EQUITY',
        'universe_tickers': ['EQUITY_BASKET'],
        'description': ('Registry backfill (kanban t_673f8430): published via trades-recon in '
                        'consumption.strategy_monthly_returns but had no registry row; FK-blocked '
                        'strategy_configs. Research outcome: auto-dropped, insufficient trade count '
                        '(6 trades / 6.3y, negative alpha vs SPY). Non-deployable.'),
    },
]

def main():
    comp = json.load(open('/home/ubuntu/.hermes/kanban/boards/qr_frontend/attachments/t_abb57f07/annual_compounds.json'))
    verified = set(comp['verified'])
    legacy = set(comp['keep_legacy_values'])
    assert len(verified) == 27 and len(legacy) == 3 and not (verified & legacy)

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT strategy_id FROM consumption.strategy_monthly_returns")
    published = {r[0] for r in cur.fetchall()}
    assert len(published) == 30 and published == verified | legacy

    # --- step 1: registry backfill ---
    reg_inserted = 0
    for r in REGISTRY_BACKFILL:
        cur.execute("""
            INSERT INTO gold.strategy_registry
                (strategy_id, name, asset_class, universe_tickers, frequency,
                 execution_mode, status, description)
            VALUES (%(strategy_id)s, %(name)s, %(asset_class)s, %(universe_tickers)s,
                    'daily', 'SIMULATION', 'retired', %(description)s)
            ON CONFLICT (strategy_id) DO NOTHING
        """, r)
        reg_inserted += cur.rowcount
    print(f'registry backfill inserted: {reg_inserted}')

    cur.execute("SELECT strategy_id FROM gold.strategy_registry WHERE strategy_id = ANY(%s)", (list(published),))
    missing = published - {row[0] for row in cur.fetchall()}
    assert not missing, f'still missing from registry: {missing}'

    # --- step 2: flag upserts ---
    updated, inserted = 0, 0
    for sid in sorted(published):
        if sid in verified:
            val, base_desc, marker = False, DESC_CORRECTED, MARKER_CORRECTED
        else:
            val, base_desc, marker = True, DESC_LEGACY, MARKER_LEGACY
        cur.execute("""
            SELECT id, description FROM gold.strategy_configs
            WHERE strategy_id=%s AND config_key='trades_sum_is_book_annual_return'
        """, (sid,))
        row = cur.fetchone()
        if row:
            rid, desc = row
            desc = desc or ''
            new_desc = desc if marker in desc else (desc + ' | ' + marker if desc else marker)
            cur.execute("""
                UPDATE gold.strategy_configs
                SET config_value=%s, description=%s, updated_at=now()
                WHERE id=%s
            """, (Json(val), new_desc, rid))
            updated += 1
        else:
            cur.execute("""
                INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value, description, updated_at)
                VALUES (%s, 'trades_sum_is_book_annual_return', %s, %s, now())
            """, (sid, Json(val), base_desc))
            inserted += 1

    conn.commit()
    print(f'flag rows: updated={updated} inserted={inserted} (total {updated+inserted}/30)')
    cur.close()
    conn.close()

if __name__ == '__main__':
    main()
