import sys, os
sys.path.insert(0, os.path.expanduser('~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts'))
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
conn = get_connection()
cur = conn.cursor()

print('=== row counts / spans (after) ===')
for t in ('XLC','XLY'):
    cur.execute("""SELECT count(*), min(date), max(date),
                   count(*) FILTER (WHERE close IS NULL) AS null_close,
                   count(*) FILTER (WHERE asset_class IS NULL OR market IS NULL) AS null_class
                   FROM silver.unified_prices WHERE ticker=%s""",(t,))
    print(t, cur.fetchone())
    cur.execute("""SELECT count(*) FROM (
                     SELECT date FROM silver.unified_prices WHERE ticker=%s
                     GROUP BY date HAVING count(*)>1) d""",(t,))
    print(t, 'duplicate dates:', cur.fetchone()[0])

print('=== XLY boundary rows ===')
cur.execute("""SELECT date, close, returns_1d FROM silver.unified_prices
WHERE ticker='XLY' AND date BETWEEN '2026-05-15' AND '2026-05-20' ORDER BY date""")
for r in cur.fetchall(): print(r)

print('=== gap scan (date - LAG > 5 calendar days) ===')
for t in ('XLC','XLY'):
    cur.execute("""
        WITH g AS (
          SELECT date, LAG(date) OVER (ORDER BY date) AS prev
          FROM silver.unified_prices WHERE ticker=%s
        )
        SELECT prev, date, date - prev AS cal_gap FROM g
        WHERE date - LAG(date) OVER (ORDER BY date) > 5
        ORDER BY date
    """,(t,))
    # above window-in-window is invalid; do it in python instead
print('(window-in-window skipped; python scan below)')

for t in ('XLC','XLY'):
    cur.execute("SELECT date FROM silver.unified_prices WHERE ticker=%s ORDER BY date",(t,))
    dates = [r[0] for r in cur.fetchall()]
    gaps = [(p,d,(d-p).days) for p,d in zip(dates, dates[1:]) if (d-p).days > 5]
    print(t, f'rows={len(dates)} span={dates[0]}..{dates[-1]} gaps>5cal:', gaps)

print('=== us_market_holidays coverage 2018..2026 ===')
cur.execute("SELECT count(*), min(holiday_date), max(holiday_date) FROM gold.us_market_holidays")
print(cur.fetchone())
conn.close()
print('EVIDENCE1 OK')
