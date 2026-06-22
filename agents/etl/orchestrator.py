#!/usr/bin/env python3
"""
Master ETL Orchestrator — Streamlined Pipeline
================================================
Only runs working data sources after DB cleanup.

ALL PATHS ARE RELATIVE TO THE HERMES WORKSPACE.
No real-path references allowed.
"""
import sys, os, json, subprocess
from datetime import datetime, timezone

# Everything lives inside the Hermes workspace
WORKSPACE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')

# Use system python3 (psycopg2 and dotenv now installed)
VENV_PYTHON = 'python3'

BRONZE = [
    ('yfinance_vix', 'bronze/yfinance/ingest_vix.py'),
    ('binance',  'bronze/binance/ingest_binance.py'),
    ('binance_funding_rates', 'bronze/binance/ingest_funding_rates.py'),
    ('binance_crypto', 'bronze/binance/crypto_ingest.py'),
]

SILVER = [
    ('clean_prices',    'silver/clean_prices.py'),
    ('clean_earnings',  'silver/clean_earnings.py'),
    ('tech_indicators', 'silver/compute_technical_indicators.py'),
    ('market_indices',  'silver/sync_market_indices.py'),
    ('asset_registry',  'silver/clean_asset_registry.py'),
]

GOLD = [
    ('gold_builder',          'gold/gold_builder.py'),
    ('equity_kpis',          'gold/equity/build_equity_kpis.py'),
    ('stock_metrics',        'gold/equity/build_stock_metrics.py'),
    ('stock_metrics_hist',   'gold/equity/build_stock_metrics_history.py'),
    ('earnings_signals',     'gold/equity/build_earnings_signals.py'),
    ('market_metrics',       'gold/market/build_market_metrics.py'),
    ('commodity_metrics',    'gold/commodity/build_commodity_metrics.py'),
]

CONSUMPTION = [
    ('market_overview',       'consumption/market/market_overview.py'),
    ('stocks_overview',       'consumption/command/command_stocks_overview.py'),
    ('research_signals',      'consumption/lab/lab_research_signals.py'),
    ('strategy_scores',       'consumption/lab/lab_strategy_scores.py'),
    ('performance_results',   'consumption/performance/performance_strategy_results.py'),
]

def run_script(label: str, rel_path: str) -> dict:
    """Run a single ETL script via subprocess with explicit PYTHONPATH."""
    source = os.path.join(WORKSPACE, rel_path)

    if not os.path.exists(source):
        return {'label': label, 'status': 'MISSING', 'path': source, 'stdout': '', 'stderr': '', 'rc': -1}

    # Build env with PYTHONPATH pointing to the workspace shared scripts
    proc_env = {**os.environ, 'PYTHONPATH': SHARED}

    # yfinance needs extra time for bulk downloads
    timeout = 600 if label == 'yfinance' else 300
    proc = subprocess.run(
        [VENV_PYTHON, source],
        capture_output=True, text=True, env=proc_env, cwd=WORKSPACE, timeout=timeout
    )
    status = 'OK' if proc.returncode == 0 else 'FAIL'
    return {
        'label': label,
        'status': status,
        'stdout': proc.stdout[-500:] if len(proc.stdout) > 500 else proc.stdout,
        'stderr': proc.stderr[-500:] if len(proc.stderr) > 500 else proc.stderr,
        'rc': proc.returncode,
    }

def main():
    start = datetime.now(timezone.utc)
    report = {'start': start.isoformat(), 'stages': {}}

    for stage_name, scripts in [('bronze', BRONZE), ('silver', SILVER), ('gold', GOLD), ('consumption', CONSUMPTION)]:
        print(f"\n{'='*60}\n  STAGE: {stage_name.upper()}\n{'='*60}")
        stage_results = []
        for label, rel_path in scripts:
            print(f"  → {label} ...", end=' ', flush=True)
            res = run_script(label, rel_path)
            stage_results.append(res)
            print(f"[{res['status']}]")
            if res['status'] != 'OK' and res['stderr']:
                print(f"    ⚠️  {res['stderr'][:200]}")
        report['stages'][stage_name] = stage_results

    end = datetime.now(timezone.utc)
    report['end'] = end.isoformat()
    report['duration_sec'] = (end - start).total_seconds()

    print(f"\n{'='*60}\n  SUMMARY\n{'='*60}")
    total = sum(len(v) for v in report['stages'].values())
    ok    = sum(1 for stage in report['stages'].values() for r in stage if r['status'] == 'OK')
    fail  = sum(1 for stage in report['stages'].values() for r in stage if r['status'] == 'FAIL')
    miss  = sum(1 for stage in report['stages'].values() for r in stage if r['status'] == 'MISSING')
    print(f"  Total scripts: {total}")
    print(f"  OK:     {ok}")
    print(f"  FAIL:   {fail}")
    print(f"  MISSING:{miss}")
    print(f"  Duration: {report['duration_sec']:.1f}s")

    report_path = os.path.join(WORKSPACE, 'pipeline_report.json')
    with open(report_path, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\n  Report saved: {report_path}")

if __name__ == '__main__':
    main()
