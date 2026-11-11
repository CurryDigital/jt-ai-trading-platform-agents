import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
conn = get_connection()
cur = conn.cursor()
for t in ('XLC','XLY'):
    cur.execute("""SELECT count(*), min(date), max(date),
                   count(*) FILTER (WHERE close IS NULL) AS null_close,
                   count(DISTINCT date) AS distinct_dates
                   FROM bronze.yf_prices WHERE ticker=%s""",(t,))
    print(t,'bronze:',cur.fetchone())
    cur.execute("SELECT date, open, high, low, close, volume FROM bronze.yf_prices WHERE ticker=%s ORDER BY date LIMIT 3",(t,))
    print(t,'first rows:',cur.fetchall())
    cur.execute("SELECT date, open, high, low, close, volume FROM bronze.yf_prices WHERE ticker=%s ORDER BY date DESC LIMIT 3",(t,))
    print(t,'last rows:',cur.fetchall())
# XLY boundary: old bronze tail vs new head
cur.execute("""SELECT date, close, ingested_at FROM bronze.yf_prices WHERE ticker='XLY' AND date BETWEEN '2026-05-14' AND '2026-05-21' ORDER BY date""")
print('XLY boundary bronze:', cur.fetchall())
conn.close()
print('VERIFY OK')
