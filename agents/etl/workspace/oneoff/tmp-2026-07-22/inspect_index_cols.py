import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute("""
SELECT table_schema, table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema IN ('gold','consumption')
  AND table_name IN ('index_metrics','dashboard_market_overview','dashboard_indices')
ORDER BY table_schema, table_name, ordinal_position;
""")
for row in cur.fetchall():
    print(row)
conn.close()
