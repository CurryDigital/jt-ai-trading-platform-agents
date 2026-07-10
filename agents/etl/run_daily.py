#!/usr/bin/env python3
"""
qr_etl Daily Orchestrator — Goal 5
===================================
Runs the 4-stage regime detection pipeline end-to-end.
Fails loudly, retries bronze ingest, logs everything.

Usage:
    python run_daily.py              # normal daily run
    python run_daily.py --backfill   # full history rebuild
"""
import sys, os, time, traceback, subprocess
from datetime import datetime, timezone

WORKSPACE = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.join(WORKSPACE, 'shared', 'scripts')
LOG_DIR = os.path.join(WORKSPACE, 'logs')
VENV_PYTHON = 'python3'

os.makedirs(LOG_DIR, exist_ok=True)

# ── Stage definitions ─────────────────────────────────────────────────────────

BRONZE = [
    ('yfinance_prices', 'bronze/yfinance/ingest_yfinance_prices.py'),
    ('vix',            'bronze/yfinance/ingest_vix.py'),
    ('binance',        'bronze/binance/ingest_binance.py'),
    ('funding_rates',  'bronze/binance/ingest_funding_rates.py'),
    ('cot_euro_fx',    'bronze/cftc/ingest_cot_euro_fx.py'),
    ('macro_calendar', 'silver/build_macro_event_calendar.py'),
]

SILVER = [
    # 2026-06-22: clean_prices.py was a duplicate; canonical is clean_unified_prices.py.
    ('clean_prices', 'silver/clean_unified_prices.py'),
]

GOLD = [
    ('gold_builder', 'gold/gold_builder.py'),
]

CONSUMPTION = [
    ('pipeline_feed', 'consumption/pipeline/build_pipeline_feed.py'),
]


def _now() -> str:
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')


def _log(msg: str, log_file):
    line = f"[{_now()}] {msg}"
    print(line)
    log_file.write(line + '\n')
    log_file.flush()


def run_script(label: str, rel_path: str, log_file, max_retries: int = 1) -> dict:
    """Run a single ETL script. Bronze gets 3 retries with 30s backoff."""
    source = os.path.join(WORKSPACE, rel_path)
    if not os.path.exists(source):
        _log(f"  ✗ MISSING — {label} ({rel_path})", log_file)
        return {'label': label, 'status': 'MISSING', 'duration': 0.0, 'error': 'File not found'}

    proc_env = {**os.environ, 'PYTHONPATH': SHARED}
    timeout = 600 if 'yfinance' in label else 300

    duration = 0.0
    proc = None
    for attempt in range(1, max_retries + 1):
        t0 = time.time()
        proc = subprocess.run(
            [VENV_PYTHON, source],
            capture_output=True, text=True, env=proc_env, cwd=WORKSPACE, timeout=timeout
        )
        duration = time.time() - t0

        if proc.returncode == 0:
            _log(f"  ✓ {label} — {duration:.1f}s", log_file)
            return {'label': label, 'status': 'OK', 'duration': duration, 'error': None}

        err = proc.stderr.strip().split('\n')[-1] if proc.stderr else 'Unknown error'
        _log(f"  ✗ {label} — attempt {attempt}/{max_retries} — {err[:120]}", log_file)

        if attempt < max_retries:
            _log(f"    → retrying in 30s...", log_file)
            time.sleep(30)

    return {'label': label, 'status': 'FAIL', 'duration': duration,
            'error': (proc.stderr.strip() if proc and proc.stderr else 'Unknown error')}


def run_stage(name: str, scripts: list, log_file, retries: int = 1) -> dict:
    """Run all scripts in a stage. Returns stage summary."""
    _log(f"\n{'='*50}", log_file)
    _log(f"Stage — {name}", log_file)
    _log(f"{'='*50}", log_file)

    results = []
    t0 = time.time()
    for label, rel_path in scripts:
        res = run_script(label, rel_path, log_file, max_retries=retries)
        results.append(res)
    stage_dur = time.time() - t0

    ok = sum(1 for r in results if r['status'] == 'OK')
    fail = sum(1 for r in results if r['status'] == 'FAIL')
    missing = sum(1 for r in results if r['status'] == 'MISSING')
    status = 'OK' if fail == 0 and missing == 0 else 'FAIL'

    _log(f"  → {ok} OK, {fail} FAIL, {missing} MISSING — {stage_dur:.1f}s", log_file)
    return {'name': name, 'status': status, 'duration': stage_dur, 'results': results}


def get_today_regime() -> dict:
    """Fetch today's regime from the database.

    Note: imports regime/regime_rules from the signals agent (split out from
    ETL on 2026-06-22). This is a read-only display call — etl uses it to
    annotate the run log with which strategies the signal agent will gate-in
    later. If you'd rather avoid the cross-agent reach, replace this with a
    SELECT on gold.regime_label."""
    sys.path.insert(0, SHARED)
    _SIGNALS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), '..', 'signals'))
    if _SIGNALS_DIR not in sys.path:
        sys.path.insert(0, _SIGNALS_DIR)
    os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
    from db import get_connection
    from regime.regime_rules import get_active_strategies
    try:
        return get_active_strategies()
    except Exception:
        return {'date': str(datetime.now().date()), 'regime': 'UNKNOWN',
                'active_strategies': [], 'override_used': False, 'confidence': 0.0}


def get_pipeline_summary() -> dict:
    """Fetch pipeline summary for run log / report from database.

    Mirrors the consumption script output so reports stay consistent."""
    sys.path.insert(0, SHARED)
    from db import get_connection
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute("""
            SELECT
                COUNT(*) FILTER (WHERE stage = 'experimental') AS experimental,
                COUNT(*) FILTER (WHERE stage = 'near_golden')  AS near_golden,
                COUNT(*) FILTER (WHERE stage = 'golden')       AS golden,
                COUNT(*) FILTER (WHERE stage = 'deployed')    AS deployed,
                COUNT(*) AS total
            FROM gold.v_pipeline_ui_feed
        """)
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {
                'experimental': row[0] or 0,
                'near_golden': row[1] or 0,
                'golden': row[2] or 0,
                'deployed': row[3] or 0,
                'total': row[4] or 0,
            }
    except Exception as e:
        return {'error': str(e)}
    return {'error': 'no data'}


def main():
    today = datetime.now(timezone.utc).strftime('%Y%m%d')
    log_path = os.path.join(LOG_DIR, f'run_{today}.log')
    log_file = open(log_path, 'w')

    _log(f"qr_etl daily run — {_now()}", log_file)
    _log(f"{'='*50}", log_file)

    total_t0 = time.time()
    exit_code = 0

    # Stage 1 — BRONZE (ingest with retries)
    stage1 = run_stage('INGEST', BRONZE, log_file, retries=3)
    if stage1['status'] != 'OK':
        _log(f"\nABORT: Stage 1 INGEST failed. Gold will not run on stale data.", log_file)
        exit_code = 1

    # Stage 2 — SILVER (clean)
    stage2 = run_stage('SILVER', SILVER, log_file, retries=1)
    if stage2['status'] != 'OK' and exit_code == 0:
        _log(f"\nABORT: Stage 2 SILVER failed. Gold will not run on dirty data.", log_file)
        exit_code = 1

    # Stage 3 — GOLD (build analytics)
    stage3 = None
    if exit_code == 0:
        stage3 = run_stage('GOLD', GOLD, log_file, retries=1)
        if stage3['status'] != 'OK':
            _log(f"\nWARNING: Stage 3 GOLD failed. Yesterday's regime_label is still valid.", log_file)
            # Do NOT abort — yesterday's labels are still usable

    # Stage 3.5 — CONSUMPTION (UI feeds)
    stage35 = None
    if exit_code == 0:
        stage35 = run_stage('CONSUMPTION', CONSUMPTION, log_file, retries=1)
        if stage35['status'] != 'OK':
            _log(f"\nWARNING: Stage 3.5 CONSUMPTION failed. UI feeds may be stale.", log_file)

    # Stage 4 — REPORT
    _log(f"\n{'='*50}", log_file)
    _log(f"Stage — REPORT", log_file)
    _log(f"{'='*50}", log_file)
    try:
        regime = get_today_regime()
        eia_note = " (EIA day)" if regime.get('eia_day') else ""
        _log(f"  Regime today:        {regime['regime']}{eia_note}", log_file)
        _log(f"  Active strategies:   {regime['active_strategies']}", log_file)
        _log(f"  Override used:       {regime['override_used']}", log_file)
        _log(f"  Confidence:          {regime['confidence']:.4f}", log_file)
    except Exception as e:
        _log(f"  WARNING: Could not fetch today's regime: {e}", log_file)

    try:
        psum = get_pipeline_summary()
        if 'error' in psum:
            _log(f"  WARNING: Pipeline summary: {psum['error']}", log_file)
        else:
            _log(f"  Pipeline summary:    experimental={psum['experimental']}, near_golden={psum['near_golden']}, golden={psum['golden']}, deployed={psum['deployed']}, total={psum['total']}", log_file)
    except Exception as e:
        _log(f"  WARNING: Could not fetch pipeline summary: {e}", log_file)

    total_dur = time.time() - total_t0

    # Summary
    _log(f"\n{'─'*50}", log_file)
    _log(f"Stage 1 INGEST       {'✓' if stage1['status']=='OK' else '✗'} {stage1['duration']:.1f}s", log_file)
    _log(f"Stage 2 SILVER       {'✓' if stage2['status']=='OK' else '✗'} {stage2['duration']:.1f}s", log_file)
    if stage3:
        _log(f"Stage 3 GOLD         {'✓' if stage3['status']=='OK' else '✗'} {stage3['duration']:.1f}s", log_file)
    else:
        _log(f"Stage 3 GOLD         — skipped (earlier stage failed)", log_file)
    if stage35:
        _log(f"Stage 3.5 CONSUMPTION {'✓' if stage35['status']=='OK' else '✗'} {stage35['duration']:.1f}s", log_file)
    else:
        _log(f"Stage 3.5 CONSUMPTION — skipped (earlier stage failed)", log_file)
    _log(f"Stage 4 REPORT       ✓", log_file)
    _log(f"{'─'*50}", log_file)
    _log(f"Total runtime:       {total_dur:.1f}s", log_file)
    _log(f"Exit code:           {exit_code}", log_file)
    _log(f"{'='*50}", log_file)

    log_file.close()
    print(f"\nLog saved: {log_path}")
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
