#!/usr/bin/env python3
"""One-off: raise assigned_capital $10k -> $100k for COMM_GoldSilver_Ratio_MeanRev_VolTarget.
Kanban t_0a520c52. Write: gold.strategy_registry only.
"""
import sys, os

_HERE = os.path.dirname(os.path.abspath(__file__))
_ETL_SHARED = os.path.normpath(os.path.join(_HERE, '..', '..', 'shared', 'scripts'))
if _ETL_SHARED not in sys.path:
    sys.path.insert(0, _ETL_SHARED)

from db import get_connection

SID = 'COMM_GoldSilver_Ratio_MeanRev_VolTarget'

conn = get_connection()
cur = conn.cursor()
try:
    cur.execute("""
        UPDATE gold.strategy_registry
        SET assigned_capital = 100000
        WHERE strategy_id = %s
    """, (SID,))
    print(f"rows updated: {cur.rowcount}")
    cur.execute("""
        SELECT strategy_id, execution_mode, assigned_capital
        FROM gold.strategy_registry WHERE strategy_id = %s
    """, (SID,))
    print("post-update row:", cur.fetchone())
    conn.commit()
    print("COMMIT ok")
except Exception:
    conn.rollback()
    raise
finally:
    cur.close()
    conn.close()
