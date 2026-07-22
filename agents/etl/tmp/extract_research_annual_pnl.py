"""Extract annual_pnl from research backtest result JSONs."""
import json, os, glob

BASE = "/home/ubuntu/.hermes/profiles/qr_research/workspace"

# Map strategy_id to result JSON path(s)
JSONS = {
    "HK_LowVol_TrendFilter_Weekly": [
        "HK_LowVol_TrendFilter_Weekly_results.json",
        "HK_LowVol_TrendFilter_Weekly_qa_reproduce/HK_LowVol_TrendFilter_Weekly_results.json",
    ],
    "HK_LowVol_Weekly": [
        "HK_LowVol_Weekly_results.json",
        "HK_LowVol_Weekly_qa_reproduce/HK_LowVol_Weekly_results.json",
    ],
    "HK_Quality_BlueChips": [
        "HK_Quality_BlueChips_expanded_results.json",
        "HK_Quality_BlueChips_original_results.json",
    ],
    "ETF_HK_Balanced_Trend": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_US_Sector_Relative_Momentum": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_Global_Risk_Parity_VolTarget": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_Dividend_Aristocrats_Treasury_Barbell": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_Covered_Call_Income_Rotation": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_Multi_Asset_Tactical_Allocation": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_REIT_Dividend_Momentum": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_HY_Credit_Carry": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_Defensive_Equity_Income": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
    "ETF_Small_Cap_Momentum": ["etf_replacement_8_results.json", "etf_corrected_backtest_results.json", "etf_backtest_results.json"],
}

def find_annual_pnl(data, sid):
    """Recursively search for annual_pnl keys in JSON."""
    results = {}
    if isinstance(data, dict):
        if "annual_pnl_2024" in data or "annual_pnl_2025" in data or "annual_pnl_2026" in data:
            results = {
                "2024": data.get("annual_pnl_2024"),
                "2025": data.get("annual_pnl_2025"),
                "2026": data.get("annual_pnl_2026"),
            }
            return results
        for k, v in data.items():
            if sid.lower() in k.lower() or k.lower() == sid.lower().replace("_", ""):
                r = find_annual_pnl(v, sid)
                if r:
                    return r
        for v in data.values():
            r = find_annual_pnl(v, sid)
            if r:
                return r
    elif isinstance(data, list):
        for item in data:
            r = find_annual_pnl(item, sid)
            if r:
                return r
    return {}

for sid, paths in JSONS.items():
    print(f"\n=== {sid} ===")
    for p in paths:
        full = os.path.join(BASE, p)
        if not os.path.exists(full):
            print(f"  {p}: FILE NOT FOUND")
            continue
        with open(full) as f:
            data = json.load(f)
        r = find_annual_pnl(data, sid)
        print(f"  {p}: {r}")
