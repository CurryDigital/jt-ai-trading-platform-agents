import os, csv
import psycopg2
from psycopg2.extras import RealDictCursor

conn = psycopg2.connect(
    host=os.environ['PGHOST'],
    dbname=os.environ['PGDATABASE'],
    user=os.environ['PGUSER'],
    password=os.environ['PGPASSWORD'],
)
cur = conn.cursor(cursor_factory=RealDictCursor)

THIRTY = [
    'btc_funding_mean_rev_short','cl_cot_trend','cot_contrarian_extreme','earnings_vol_crush_carry',
    'ETF_Covered_Call_Income_Rotation','ETF_Defensive_Equity_Income','ETF_Dividend_Aristocrats_Treasury_Barbell',
    'ETF_Global_Risk_Parity_VolTarget','ETF_HK_Balanced_Trend','ETF_HY_Credit_Carry','ETF_Multi_Asset_Tactical_Allocation',
    'ETF_REIT_Dividend_Momentum','ETF_Small_Cap_Momentum','ETF_US_Sector_Relative_Momentum','gc_cot_contrarian_inverse',
    'nfp_equity_drift_long','pead_long','pead_short_negative_surprise','S9_MACD_Momentum_V2','US_STK_AI_SOXX_06',
    'US_STK_CRED_CYC_04','US_STK_DEF_MOM_10','US_STK_GOLD_HDG_05','US_STK_LOWVOL_DIV_02','US_STK_MOM_LDR_01',
    'US_STK_QUAL_ROE_07','US_STK_SECTOR_PAIR_09','US_STK_SM_CAP_CRED_08','US_STK_VAL_REV_03','vix_carry_long_equity',
]

# Read latest DB values
sql = """
SELECT DISTINCT ON (s.strategy_id)
    s.strategy_id AS id,
    s.name,
    COALESCE(upper(s.asset_class::text), 'EQUITY') AS asset,
    b.win_rate_oos AS btwr,
    b.profit_factor_oos AS btpf,
    b.trade_count_oos AS trades,
    b.sharpe_oos AS sharpe,
    b.max_drawdown_oos AS dd,
    b.returns_oos AS returns_oos_pct,
    s.status AS db_status
FROM gold.strategy_research s
LEFT JOIN gold.strategy_backtest_runs b ON b.strategy_id = s.strategy_id
WHERE s.strategy_id IN %s
ORDER BY s.strategy_id, b.run_number DESC NULLS LAST, b.created_at DESC NULLS LAST
"""
cur.execute(sql, (tuple(THIRTY),))
rows = {r['id']: r for r in cur.fetchall()}

OUT = '/home/ubuntu/.hermes/kanban/boards/trading/workspaces/t_36cc0763/strategy_lab_remediation_report_2026_07_09_UPDATED.csv'
fieldnames = ['id','name','asset','btwr','btpf','trades','sharpe','dd','returns_oos_pct','db_status','backfill_note']
with open(OUT, 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for sid in THIRTY:
        r = rows.get(sid, {})
        note = ''
        if r.get('btpf') is None:
            note = 'profit_factor_oos remains NULL; no trade-level or source data available for rejected/retired strategy'
        writer.writerow({
            'id': sid,
            'name': r.get('name', ''),
            'asset': r.get('asset', ''),
            'btwr': f"{r.get('btwr') * 100:.2f}" if r.get('btwr') is not None else '',
            'btpf': f"{r.get('btpf'):.6f}" if r.get('btpf') is not None else '',
            'trades': r.get('trades', ''),
            'sharpe': f"{r.get('sharpe'):.4f}" if r.get('sharpe') is not None else '',
            'dd': f"{r.get('dd') * 100:.4f}" if r.get('dd') is not None else '',
            'returns_oos_pct': f"{r.get('returns_oos_pct') * 100:.4f}" if r.get('returns_oos_pct') is not None else '',
            'db_status': r.get('db_status', ''),
            'backfill_note': note,
        })

print(f"Wrote updated CSV: {OUT}")
print("Rows:")
for sid in THIRTY:
    r = rows.get(sid, {})
    print(f"  {sid}: btpf={r.get('btpf')}, btwr={r.get('btwr')}, trades={r.get('trades')}, status={r.get('db_status')}")

conn.close()
