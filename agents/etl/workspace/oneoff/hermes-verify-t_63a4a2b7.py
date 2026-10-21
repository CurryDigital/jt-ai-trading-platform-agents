#!/usr/bin/env python3
"""Ad-hoc verification for t_63a4a2b7 (WRITE_SIGNAL etf_trend_overlay_mom12m_v1).

Asserts the end-state of every change made this run:
 1. build_rotation_signals.py compiles; handler+config present
 2. ticker_scores: 6 rows matching the research signal file (weights + mom252 meta)
 3. registry: universe includes CASH; cap override = 1.0
 4. paper book: IEF position open
 5. v_pipeline_ui_feed + ETL feed JSON contain the strategy
 6. research workspace feed copies refreshed and contain the strategy
 7. crisis_safe_haven_vt_19: description + annual pnl backfilled
 8. strategy_backtest_trades: tsmom_07 (run 2) + mom12m (run 1) rows present
"""
import json
import py_compile
import sys

sys.path.insert(0, '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/shared/scripts')
from db import get_connection

SID = 'etf_trend_overlay_mom12m_v1'
fails = []


def check(name, ok, detail=''):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")
    if not ok:
        fails.append(name)


# 1. engine file compiles + handler wired
py_compile.compile(
    '/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/signals/pipeline/build_rotation_signals.py',
    doraise=True)
src = open('/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/signals/pipeline/build_rotation_signals.py').read()
check('engine compiles; config+handler+dispatch present',
      "'custom': 'trend_overlay_mom12m'" in src
      and 'def trend_overlay_mom12m_rows' in src
      and "cfg.get('custom') == 'trend_overlay_mom12m'" in src)

conn = get_connection()
cur = conn.cursor()

# 2. ticker scores vs research signal file
cur.execute("""SELECT ticker, signal_action, score, position_status, signal_source
               FROM gold.strategy_ticker_scores WHERE strategy_id=%s""", (SID,))
rows = {r[0]: r for r in cur.fetchall()}
exp = {'SPY': ('BUY', 25.0), 'QQQ': ('BUY', 25.0), 'GLD': ('BUY', 25.0),
       'IEF': ('BUY', 25.0), 'TLT': ('HOLD', 0.0), 'CASH': ('HOLD', 0.0)}
ok = len(rows) == 6 and all(
    rows.get(t) and rows[t][1] == a and abs(float(rows[t][2]) - w) < 1e-6
    and rows[t][3] == 'PAPER' and rows[t][4] == 'computed'
    for t, (a, w) in exp.items())
check('ticker_scores 6 rows match research signal file', ok, str({t: (rows[t][1], float(rows[t][2])) for t in rows}))

cur.execute("""SELECT criteria_met->>'signal_date', criteria_met->'mom252'
               FROM gold.strategy_ticker_scores WHERE strategy_id=%s LIMIT 1""", (SID,))
sd, mom = cur.fetchone()
file_scores = {'SPY': 0.2374, 'QQQ': 0.2817, 'GLD': 0.2523, 'TLT': -0.0269, 'IEF': 0.0055}
ok = all(abs(mom[t] - v) < 5e-5 for t, v in file_scores.items())
check('mom252 meta matches signal file scores (4dp)', ok, f'signal_date={sd} mom={mom}')

# 3. registry + cap
cur.execute("SELECT universe_tickers FROM gold.strategy_registry WHERE strategy_id=%s", (SID,))
check('registry universe includes CASH', 'CASH' in cur.fetchone()[0])
cur.execute("SELECT config_value FROM gold.strategy_configs WHERE strategy_id=%s AND config_key='max_position_pct'", (SID,))
check('cap override = 1.0', float(cur.fetchone()[0]) == 1.0)

# 4. paper book
cur.execute("""SELECT ticker, n_shares, ROUND(n_shares*entry_price,2)
               FROM gold.paper_trades_synthetic WHERE strategy_id=%s AND status='open'""", (SID,))
book = cur.fetchall()
check('paper book open (IEF leg filled)', len(book) == 1 and book[0][0] == 'IEF', str(book))

# 5. view + ETL feed
cur.execute("SELECT id, stage, sharpe, trades FROM gold.v_pipeline_ui_feed WHERE id=%s", (SID,))
v = cur.fetchone()
check('v_pipeline_ui_feed shows strategy', v is not None, str(v))
feed = json.load(open('/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/consumption/pipeline/pipeline_feed.json'))
check('ETL pipeline_feed.json contains strategy',
      SID in [r['id'] for r in feed['data']], f"rows={len(feed['data'])}")

# 6. research workspace feed copies
rf = json.load(open('/home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed.json'))
fa = json.load(open('/home/ubuntu/.hermes/profiles/qr_research/workspace/pipeline_feed_full_approved_2026-08-09.json'))
check('research feed copies refreshed',
      SID in [r['id'] for r in rf['data']]
      and SID in [r['strategy_id'] for r in fa['strategies']],
      f"feed={len(rf['data'])} full_approved={fa['approved_count']}")

# 7. crisis backfill
cur.execute("""SELECT description IS NOT NULL,
               (SELECT annual_pnl_2025 FROM gold.strategy_backtest_runs
                 WHERE strategy_id='crisis_safe_haven_vt_19' AND run_number=1),
               (SELECT annual_pnl_2026 FROM gold.strategy_backtest_runs
                 WHERE strategy_id='crisis_safe_haven_vt_19' AND run_number=1)
               FROM gold.strategy_registry WHERE strategy_id='crisis_safe_haven_vt_19'""")
d, p25, p26 = cur.fetchone()
check('crisis_safe_haven_vt_19 backfilled', d and abs(float(p25) - 0.2804) < 1e-9
      and abs(float(p26) - 0.0132) < 1e-9, f'desc={d} 2025={p25} 2026={p26}')

# 8. backtest trades
cur.execute("""SELECT strategy_id, period, COUNT(*) FROM gold.strategy_backtest_trades
               WHERE strategy_id IN ('etf_tsmom_basket_07', %s)
               GROUP BY 1,2 ORDER BY 1,2""", (SID,))
counts = {(r[0], r[1]): r[2] for r in cur.fetchall()}
check('backtest trades ingested',
      counts.get(('etf_tsmom_basket_07', 'IS')) == 27
      and counts.get(('etf_tsmom_basket_07', 'OOS')) == 15
      and counts.get((SID, 'OOS')) == 18, str(counts))

conn.close()
print()
print('AD-HOC VERIFICATION:', 'FAILED: ' + ', '.join(fails) if fails else 'ALL CHECKS PASSED')
sys.exit(1 if fails else 0)
