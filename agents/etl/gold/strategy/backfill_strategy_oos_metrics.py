import os, csv, json, math
from decimal import Decimal, InvalidOperation
from typing import Optional
import psycopg2
from psycopg2.extras import RealDictCursor

DB = dict(
    host=os.environ['PGHOST'],
    dbname=os.environ['PGDATABASE'],
    user=os.environ['PGUSER'],
    password=os.environ['PGPASSWORD'],
)

CSV_PATH = '/home/ubuntu/.hermes/profiles/qr_research/workspace/strategy_lab_remediation_report_2026_07_09.csv'
ETF_JSON = '/home/ubuntu/.hermes/profiles/qr_research/workspace/etf_oos_recomputed_2026-07-09.json'
US_STK_JSON = '/home/ubuntu/.hermes/profiles/qr_research/workspace/us_stock_pipeline_10_final_results_2026-07-08_REMEDIATED.json'

THIRTY = [
    'btc_funding_mean_rev_short','cl_cot_trend','cot_contrarian_extreme','earnings_vol_crush_carry',
    'ETF_Covered_Call_Income_Rotation','ETF_Defensive_Equity_Income','ETF_Dividend_Aristocrats_Treasury_Barbell',
    'ETF_Global_Risk_Parity_VolTarget','ETF_HK_Balanced_Trend','ETF_HY_Credit_Carry','ETF_Multi_Asset_Tactical_Allocation',
    'ETF_REIT_Dividend_Momentum','ETF_Small_Cap_Momentum','ETF_US_Sector_Relative_Momentum','gc_cot_contrarian_inverse',
    'nfp_equity_drift_long','pead_long','pead_short_negative_surprise','S9_MACD_Momentum_V2','US_STK_AI_SOXX_06',
    'US_STK_CRED_CYC_04','US_STK_DEF_MOM_10','US_STK_GOLD_HDG_05','US_STK_LOWVOL_DIV_02','US_STK_MOM_LDR_01',
    'US_STK_QUAL_ROE_07','US_STK_SECTOR_PAIR_09','US_STK_SM_CAP_CRED_08','US_STK_VAL_REV_03','vix_carry_long_equity',
]

def safe_decimal(s):
    if s is None or s == '' or str(s).lower() in ('nan','none'):
        return None
    try:
        return Decimal(s)
    except InvalidOperation:
        return None

# ---- load sources ----
csv_rows = {}
with open(CSV_PATH) as f:
    for r in csv.DictReader(f):
        csv_rows[r['id']] = r

etf_json = json.load(open(ETF_JSON))
us_json = json.load(open(US_STK_JSON))

conn = psycopg2.connect(**DB)
conn.autocommit = False
cur = conn.cursor(cursor_factory=RealDictCursor)
# Add/widen columns in registry if needed
print("\nEnsuring gold.strategy_registry columns exist and have sufficient width...")
cur.execute("""
SELECT column_name, numeric_precision, numeric_scale
FROM information_schema.columns
WHERE table_schema='gold' AND table_name='strategy_registry'
  AND column_name IN ('profit_factor_oos', 'win_rate_oos', 'max_drawdown_oos')
""")
reg_cols = {r['column_name']: (r['numeric_precision'], r['numeric_scale']) for r in cur.fetchall()}
if 'profit_factor_oos' not in reg_cols:
    cur.execute("ALTER TABLE gold.strategy_registry ADD COLUMN profit_factor_oos numeric")
    print("  Added profit_factor_oos")
if reg_cols.get('win_rate_oos') != (8, 4):
    cur.execute("ALTER TABLE gold.strategy_registry ALTER COLUMN win_rate_oos TYPE numeric(8,4)")
    print("  Widened win_rate_oos to numeric(8,4)")
if reg_cols.get('max_drawdown_oos') != (8, 4):
    cur.execute("ALTER TABLE gold.strategy_registry ALTER COLUMN max_drawdown_oos TYPE numeric(8,4)")
    print("  Widened max_drawdown_oos to numeric(8,4)")

# One-time restore of DB profit_factor_oos for strategies that had a pre-existing DB value
# which was accidentally overwritten by a prior JSON-only pass.
RESTORE_PF = {
    'ETF_HK_Balanced_Trend': Decimal('2.0733'),
}
print("\nRestoring pre-existing DB profit_factor_oos values where needed...")
for sid, pf in RESTORE_PF.items():
    cur.execute("""
        UPDATE gold.strategy_backtest_runs
        SET profit_factor_oos = %s
        WHERE strategy_id = %s AND profit_factor_oos != %s
    """, (pf, sid, pf))
    if cur.rowcount:
        print(f"  Restored {sid} to {pf}")

# Precompute PF from DB trades for each strategy_id
print("\nComputing PF from strategy_backtest_trades where available...")
trade_pf = {}
for sid in THIRTY:
    cur.execute("SELECT pnl_pct FROM gold.strategy_backtest_trades WHERE strategy_id=%s", (sid,))
    pnls = [r['pnl_pct'] for r in cur.fetchall() if r['pnl_pct'] is not None]
    pnls = [p for p in pnls if p and not p.is_nan()]
    if pnls:
        gross_profit = sum(p for p in pnls if p > 0)
        gross_loss = abs(sum(p for p in pnls if p < 0))
        pf = round(gross_profit / gross_loss, 6) if gross_loss else None
        trade_pf[sid] = pf
        print(f"  {sid}: {len(pnls)} trades, PF={pf}")

# Resolve current DB PF per strategy
print("\nReading current DB profit_factor_oos...")
cur_db_pf = {}
cur.execute("""
    SELECT DISTINCT ON (strategy_id) strategy_id, profit_factor_oos
    FROM gold.strategy_backtest_runs
    WHERE strategy_id IN %s
    ORDER BY strategy_id, run_number DESC
""", (tuple(THIRTY),))
for r in cur.fetchall():
    cur_db_pf[r['strategy_id']] = r['profit_factor_oos']

# Resolve target PF per strategy (prefer DB over JSON/CSV unless trade-level data exists)
print("\nResolving target PF per strategy...")
target_pf = {}
for sid in THIRTY:
    db_pf = cur_db_pf.get(sid)
    pf = None
    source = None
    if sid in trade_pf:
        pf = trade_pf[sid]
        source = 'db_trades'
    elif db_pf is not None:
        pf = db_pf
        source = 'db_existing'
    elif sid in etf_json and etf_json[sid].get('profit_factor') is not None:
        pf = round(Decimal(str(etf_json[sid]['profit_factor'])), 6)
        source = 'etf_oos_recomputed_json'
    else:
        csv_btpf = safe_decimal(csv_rows.get(sid, {}).get('btpf'))
        if csv_btpf is not None:
            pf = csv_btpf
            source = 'remediation_csv'
    target_pf[sid] = (pf, source)
    if pf is not None:
        print(f"  {sid}: target PF={pf} from {source}")
    else:
        print(f"  {sid}: NO PF source found")

# Update strategy_backtest_runs for all rows of these 30 strategies
print("\nUpdating gold.strategy_backtest_runs profit_factor_oos...")
updated = 0
for sid, (pf, source) in target_pf.items():
    if pf is None:
        continue
    cur.execute("""
        UPDATE gold.strategy_backtest_runs
        SET profit_factor_oos = %s
        WHERE strategy_id = %s
          AND (profit_factor_oos IS NULL OR profit_factor_oos != %s)
    """, (pf, sid, pf))
    updated += cur.rowcount
print(f"Updated {updated} rows in strategy_backtest_runs")

# Also update other OOS metrics for ETF strategies from the JSON only where currently NULL or zero
print("\nUpdating ETF OOS metrics from recomputed JSON (where currently NULL or zero)...")
metric_updates = 0
for sid, data in etf_json.items():
    if sid not in THIRTY:
        continue
    mapping = {
        'sharpe': 'sharpe_oos',
        'total_ret': 'returns_oos',
        'max_dd': 'max_drawdown_oos',
        'trade_count': 'trade_count_oos',
        'win_rate': 'win_rate_oos',
    }
    for json_key, db_col in mapping.items():
        val = data.get(json_key)
        if val is None:
            continue
        val = Decimal(str(val))
        cur.execute(f"""
            UPDATE gold.strategy_backtest_runs
            SET {db_col} = %s
            WHERE strategy_id = %s AND ({db_col} IS NULL OR {db_col} = 0)
        """, (val, sid))
        metric_updates += cur.rowcount
print(f"Updated {metric_updates} metric cells from ETF JSON")

# Sync registry from latest backtest run
print("\nSyncing gold.strategy_registry from latest backtest runs...")
cur.execute("""
UPDATE gold.strategy_registry r
SET
    win_rate_oos = b.win_rate_oos * 100,
    profit_factor_oos = b.profit_factor_oos,
    trade_count_oos = b.trade_count_oos,
    max_drawdown_oos = ABS(b.max_drawdown_oos) * 100,
    sharpe_oos = b.sharpe_oos,
    updated_at = NOW()
FROM (
    SELECT DISTINCT ON (strategy_id)
        strategy_id,
        win_rate_oos,
        profit_factor_oos,
        trade_count_oos,
        max_drawdown_oos,
        sharpe_oos
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_id, run_number DESC
) b
WHERE r.strategy_id = b.strategy_id
  AND b.profit_factor_oos IS NOT NULL
""")
print(f"Synced {cur.rowcount} registry rows")

conn.commit()
print("\nCommitted")

# ---- verification ----
print("\n--- Verification: approved/backtesting 30 with NULL btpf ---")
cur.execute("""
SELECT s.strategy_id, s.status, b.profit_factor_oos
FROM gold.strategy_research s
LEFT JOIN (
    SELECT DISTINCT ON (strategy_id) strategy_id, profit_factor_oos
    FROM gold.strategy_backtest_runs
    ORDER BY strategy_id, run_number DESC
) b ON b.strategy_id = s.strategy_id
WHERE s.strategy_id IN %s AND s.status IN ('approved','backtesting')
ORDER BY s.strategy_id
""", (tuple(THIRTY),))
for r in cur.fetchall():
    print(f"  {r['strategy_id']}: {r['status']} -> btpf={r['profit_factor_oos']}")

print("\n--- v_pipeline_ui_feed sample (approved/backtesting 30) ---")
cur.execute("""
SELECT id, btwr, btpf, livewr, livepf, trades, sharpe, dd, live_pnl, db_status
FROM gold.v_pipeline_ui_feed
WHERE id IN %s AND db_status IN ('approved','backtesting')
ORDER BY id
""", (tuple(THIRTY),))
for r in cur.fetchall():
    print(dict(r))

print("\n--- registry sync sample ---")
cur.execute("""
SELECT strategy_id, win_rate_oos, profit_factor_oos, trade_count_oos, max_drawdown_oos, sharpe_oos
FROM gold.strategy_registry
WHERE strategy_id IN %s
ORDER BY strategy_id
""", (tuple(THIRTY),))
for r in cur.fetchall():
    print(dict(r))

conn.close()
