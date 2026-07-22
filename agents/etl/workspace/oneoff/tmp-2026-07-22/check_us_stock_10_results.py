"""Check US stock 10 results JSON and trade logs for annual PNL data."""
import json, os, glob

BASE = "/home/ubuntu/.hermes/profiles/qr_research/workspace"
for p in glob.glob(os.path.join(BASE, "us_stock_pipeline_10_final_results_*.json")):
    print(f"=== {os.path.basename(p)} ===")
    with open(p) as f:
        data = json.load(f)
    for name, v in data.items():
        print(f"  {name}: {v}")

print("\n=== Trade logs ===")
for p in glob.glob(os.path.join(BASE, "us_stock_pipeline_10_trade_log_*.csv")):
    print(f"  {os.path.basename(p)}: exists")
