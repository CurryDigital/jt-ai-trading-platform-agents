"""Check S9 and vix status."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'shared', 'scripts'))
from db import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute("""
    SELECT r.strategy_id, r.status, r.priority, res.status as research_status
    FROM gold.strategy_registry r
    JOIN gold.strategy_research res ON res.strategy_id = r.strategy_id
    WHERE r.strategy_id IN ('S9_MACD_Momentum_V2', 'vix_carry_long_equity');
""")
for row in cur.fetchall():
    print(row)

conn.close()
