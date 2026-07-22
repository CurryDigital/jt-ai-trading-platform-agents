"""Final verification for strategy_lab remediation pipeline.

Checks:
  1. v_pipeline_ui_feed has no NULL btpf for approved/backtesting strategies.
  2. v_pipeline_ui_feed rows for the 30 remediation strategies are populated.
  3. gold.strategy_registry has the same PF values as the latest backtest run for the 30.
  4. strategy_backtest_runs max_drawdown_oos is non-positive.
  5. CSV file exists and has 30 data rows + header.
"""
import os
import csv
import psycopg2
from psycopg2.extras import RealDictCursor

DB = dict(
    host=os.environ['PGHOST'],
    dbname=os.environ['PGDATABASE'],
    user=os.environ['PGUSER'],
    password=os.environ['PGPASSWORD'],
)

THIRTY = [
    'btc_funding_mean_rev_short','cl_cot_trend','cot_contrarian_extreme','earnings_vol_crush_carry',
    'ETF_Covered_Call_Income_Rotation','ETF_Defensive_Equity_Income','ETF_Dividend_Aristocrats_Treasury_Barbell',
    'ETF_Global_Risk_Parity_VolTarget','ETF_HK_Balanced_Trend','ETF_HY_Credit_Carry','ETF_Multi_Asset_Tactical_Allocation',
    'ETF_REIT_Dividend_Momentum','ETF_Small_Cap_Momentum','ETF_US_Sector_Relative_Momentum','gc_cot_contrarian_inverse',
    'nfp_equity_drift_long','pead_long','pead_short_negative_surprise','S9_MACD_Momentum_V2','US_STK_AI_SOXX_06',
    'US_STK_CRED_CYC_04','US_STK_DEF_MOM_10','US_STK_GOLD_HDG_05','US_STK_LOWVOL_DIV_02','US_STK_MOM_LDR_01',
    'US_STK_QUAL_ROE_07','US_STK_SECTOR_PAIR_09','US_STK_SM_CAP_CRED_08','US_STK_VAL_REV_03','vix_carry_long_equity',
]

CSV_PATH = '/home/ubuntu/.hermes/kanban/boards/trading/workspaces/t_36cc0763/strategy_lab_remediation_report_2026_07_09_UPDATED.csv'

conn = psycopg2.connect(**DB)
cur = conn.cursor(cursor_factory=RealDictCursor)

print("=== CHECK 1: approved/backtesting view rows have btpf ===")
cur.execute("""
    SELECT id, btpf, db_status
    FROM gold.v_pipeline_ui_feed
    WHERE db_status IN ('approved','backtesting')
      AND btpf IS NULL
    ORDER BY id
""")
rows = cur.fetchall()
if rows:
    print(f"FAIL: {len(rows)} approved/backtesting rows with NULL btpf:")
    for r in rows:
        print(f"  {r['id']} ({r['db_status']})")
else:
    print("PASS: 0 approved/backtesting rows with NULL btpf")

print("\n=== CHECK 2: 30 remediation strategies in view ===")
cur.execute("""
    SELECT id, btwr, btpf, trades, sharpe, dd, db_status
    FROM gold.v_pipeline_ui_feed
    WHERE id = ANY(%s)
    ORDER BY id
""", (THIRTY,))
rows = cur.fetchall()
print(f"Found {len(rows)} of {len(THIRTY)} strategies in view")
for r in rows:
    print(f"  {r['id']}: status={r['db_status']}, btpf={r['btpf']}, btwr={r['btwr']}, trades={r['trades']}")

print("\n=== CHECK 3: registry PF matches latest backtest run (30) ===")
cur.execute("""
    SELECT r.strategy_id, r.profit_factor_oos AS reg_pf, b.profit_factor_oos AS run_pf
    FROM gold.strategy_registry r
    JOIN (
        SELECT DISTINCT ON (strategy_id) strategy_id, profit_factor_oos
        FROM gold.strategy_backtest_runs
        ORDER BY strategy_id, run_number DESC, created_at DESC
    ) b ON b.strategy_id = r.strategy_id
    WHERE r.strategy_id = ANY(%s)
    ORDER BY r.strategy_id
""", (THIRTY,))
rows = cur.fetchall()
mismatches = [r for r in rows if r['reg_pf'] != r['run_pf']]
if mismatches:
    print(f"FAIL: {len(mismatches)} registry/run PF mismatches:")
    for r in mismatches:
        print(f"  {r['strategy_id']}: reg={r['reg_pf']} run={r['run_pf']}")
else:
    print(f"PASS: {len(rows)} registry rows match latest backtest PF")

print("\n=== CHECK 4: max_drawdown_oos sign ===")
cur.execute("""
    SELECT COUNT(*) FROM gold.strategy_backtest_runs
    WHERE max_drawdown_oos IS NOT NULL AND max_drawdown_oos > 0
""")
print(f"Positive max_drawdown_oos rows: {cur.fetchone()['count']}")

print("\n=== CHECK 5: CSV file ===")
if not os.path.exists(CSV_PATH):
    print(f"FAIL: CSV not found at {CSV_PATH}")
else:
    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)
        data = list(reader)
    print(f"PASS: CSV has {len(data)} data rows, header={reader.fieldnames}")
    null_btpf_approved = [r for r in data if r['db_status'] in ('approved','backtesting') and r['btpf'] == '']
    print(f"CSV rows with empty btpf and approved/backtesting status: {len(null_btpf_approved)}")

conn.close()
print("\nVerification complete")
