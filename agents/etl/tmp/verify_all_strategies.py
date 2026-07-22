#!/usr/bin/env python3
import json
import urllib.request

sids = [
    'ETF_Covered_Call_Income_Rotation',
    'ETF_Defensive_Equity_Income',
    'ETF_Dividend_Aristocrats_Treasury_Barbell',
    'ETF_Global_Risk_Parity_VolTarget',
    'ETF_HK_Balanced_Trend',
    'ETF_HY_Credit_Carry',
    'ETF_Multi_Asset_Tactical_Allocation',
    'ETF_REIT_Dividend_Momentum',
    'ETF_Small_Cap_Momentum',
    'ETF_US_Sector_Relative_Momentum',
    'HK_LowVol_TrendFilter_Weekly',
    'HK_LowVol_Weekly',
    'HK_Quality_BlueChips',
    'US_STK_DEF_MOM_10',
    'US_STK_GOLD_HDG_05',
    'US_STK_LOWVOL_DIV_02',
    'US_STK_MOM_LDR_01',
    'US_STK_QUAL_ROE_07',
    'US_STK_SM_CAP_CRED_08',
    'US_STK_VAL_REV_03',
]

print(f"{'strategy_id':40s} {'trades':>6s} {'pnl':>12s} {'monthly':>7s} {'signals':>7s} {'equity':>6s}")
print("-" * 80)
for sid in sids:
    url = f"http://localhost:8000/api/strategies/{sid}/evaluation"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
        live = data.get('metrics', {}).get('live', {})
        print(f"{sid:40s} {live.get('total_trades', 0):6d} {live.get('total_pnl', 0.0):12.2f} {len(data.get('monthly_returns', [])):7d} {len(data.get('recent_signals', [])):7d} {len(data.get('equity_curve', [])):6d}")
    except Exception as e:
        print(f"{sid:40s} ERROR: {e}")
