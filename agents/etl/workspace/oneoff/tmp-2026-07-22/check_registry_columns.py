import sys
sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

conn = get_connection()
cur = conn.cursor()
cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'gold' AND table_name = 'strategy_registry' ORDER BY ordinal_position")
for row in cur.fetchall():
    print(row[0])
conn.close()
