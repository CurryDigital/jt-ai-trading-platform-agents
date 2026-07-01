# SPLIT_TARGET: reads bronze/silver AND writes gold.
# Future: split into ingestion (Pipeline A) + signal (Pipeline B) step.
# Pipeline: MIXED (violates clean boundary — do not add to Pipeline A or B without splitting)
# Date flagged: 2026-06-13
# Action: Split into separate scripts or move gold writes to a dedicated Pipeline B script

#!/usr/bin/env python3
"""
Gold Layer Builder
Reads silver tables, writes enriched gold tables.

2026-06-22: failures now propagate. _execute_sql() increments a module-level
failure counter, and the if __name__ block at the bottom of this file calls
sys.exit(_n_stage_failures). Previously: every stage caught its own exception,
printed ❌, and the script exited 0 — operator dashboards showed green while
half the gold tables were stale.
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date
import math


# Module-level failure tracking. Each _execute_sql() call increments on
# exception; main() inspects this at the end and exits with the count.
_n_stage_failures = 0
_failed_stages: list[str] = []


def _execute_sql(label: str, sql: str) -> bool:
    """Run a single gold-layer stage. Returns True on success, False on failure.
    The failure counter ensures the script's exit code reflects reality even
    if no caller checks the return value."""
    global _n_stage_failures
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(sql)
        conn.commit()
        print(f"✅ {label}")
        return True
    except Exception as e:
        print(f"❌ {label}: {e}")
        conn.rollback()
        _n_stage_failures += 1
        _failed_stages.append(label)
        return False
    finally:
        conn.close()


def build_daily_ohlcv():
    _execute_sql("gold.daily_ohlcv", """
        INSERT INTO gold.daily_ohlcv
            (ticker, asset_class, market, date, open, high, low, close,
             volume, adjusted_close, returns_1d, primary_source, created_at, updated_at)
        SELECT ticker, asset_class, market, date, open, high, low, close,
               volume, adjusted_close, returns_1d, primary_source, NOW(), NOW()
        FROM silver.unified_prices
        WHERE date >= CURRENT_DATE - INTERVAL '14 days'
          AND open IS NOT NULL
          AND high IS NOT NULL
          AND low IS NOT NULL
          AND close IS NOT NULL
        ON CONFLICT (ticker, date) DO UPDATE SET
            asset_class = EXCLUDED.asset_class,
            market = EXCLUDED.market,
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            adjusted_close = EXCLUDED.adjusted_close,
            returns_1d = EXCLUDED.returns_1d,
            primary_source = EXCLUDED.primary_source,
            updated_at = NOW();
    """)


def build_vix_regime():
    _execute_sql("gold.vix_regime", """
        INSERT INTO gold.vix_regime (date, vix, vix_sma60, vix_z60, regime, signal_flag, updated_at)
        SELECT date, vix, vix_sma60, vix_z60,
            CASE
                WHEN vix IS NULL THEN NULL
                WHEN vix < 15 THEN 'low_vol'
                WHEN vix < 25 THEN 'normal'
                WHEN vix < 35 THEN 'high_vol'
                ELSE 'extreme'
            END,
            CASE WHEN vix_z60 IS NOT NULL AND ABS(vix_z60::numeric) > 2 THEN 1 ELSE 0 END,
            NOW()
        FROM silver.vix_indicators
        WHERE ticker = '^VIX'
        ON CONFLICT (date) DO UPDATE SET
            vix = EXCLUDED.vix,
            vix_sma60 = EXCLUDED.vix_sma60,
            vix_z60 = EXCLUDED.vix_z60,
            regime = EXCLUDED.regime,
            signal_flag = EXCLUDED.signal_flag,
            updated_at = NOW();
    """)


def build_macro_flags():
    _execute_sql("gold.macro_event_flags", """
        INSERT INTO gold.macro_event_flags
            (date, cpi_flag, nfp_flag, fed_funds_flag, eia_flag, event_flag, event_count, severity, updated_at)
        SELECT date, cpi_flag, nfp_flag, fed_funds_flag, eia_flag, event_flag,
            COALESCE(cpi_flag,0) + COALESCE(nfp_flag,0) + COALESCE(fed_funds_flag,0) + COALESCE(eia_flag,0),
            CASE
                WHEN severity = 3 THEN 'heavy'
                WHEN severity = 2 THEN 'medium'
                WHEN severity = 1 THEN 'light'
                ELSE 'none'
            END,
            NOW()
        FROM silver.macro_event_calendar
        ON CONFLICT (date) DO UPDATE SET
            cpi_flag = EXCLUDED.cpi_flag,
            nfp_flag = EXCLUDED.nfp_flag,
            fed_funds_flag = EXCLUDED.fed_funds_flag,
            eia_flag = EXCLUDED.eia_flag,
            event_flag = EXCLUDED.event_flag,
            event_count = EXCLUDED.event_count,
            severity = EXCLUDED.severity,
            updated_at = NOW();
    """)


def build_funding_metrics():
    _execute_sql("gold.crypto_funding_metrics", """
        INSERT INTO gold.crypto_funding_metrics
            (symbol, date, funding_rate_8h, funding_z, n_obs, signal_flag, regime, updated_at)
        SELECT symbol, date, funding_rate_8h, funding_z, n_obs,
            CASE WHEN funding_z IS NOT NULL AND ABS(funding_z::numeric) > 2 THEN 1 ELSE 0 END,
            CASE
                WHEN funding_rate_8h IS NULL THEN NULL
                WHEN funding_rate_8h < -0.0001 THEN 'backwardation'
                WHEN funding_rate_8h > 0.001 THEN 'contango_extreme'
                ELSE 'normal'
            END,
            NOW()
        FROM silver.funding_rates_daily
        ON CONFLICT (symbol, date) DO UPDATE SET
            funding_rate_8h = EXCLUDED.funding_rate_8h,
            funding_z = EXCLUDED.funding_z,
            n_obs = EXCLUDED.n_obs,
            signal_flag = EXCLUDED.signal_flag,
            regime = EXCLUDED.regime,
            updated_at = NOW();
    """)


def build_cot_sentiment():
    _execute_sql("gold.cot_sentiment", """
        INSERT INTO gold.cot_sentiment
            (instrument, date, report_date, noncomm_long, noncomm_short,
             net_noncomm, cot_z, sentiment, signal_flag, updated_at)
        SELECT instrument, date, report_date, noncomm_long, noncomm_short, net_noncomm, cot_z,
            CASE
                WHEN net_noncomm IS NULL THEN NULL
                WHEN net_noncomm > 50000 THEN 'bullish'
                WHEN net_noncomm < -50000 THEN 'bearish'
                ELSE 'neutral'
            END,
            CASE WHEN cot_z IS NOT NULL AND ABS(cot_z::numeric) > 1.5 THEN 1 ELSE 0 END,
            NOW()
        FROM silver.cot_euro_fx_daily
        ON CONFLICT (instrument, date) DO UPDATE SET
            report_date = EXCLUDED.report_date,
            noncomm_long = EXCLUDED.noncomm_long,
            noncomm_short = EXCLUDED.noncomm_short,
            net_noncomm = EXCLUDED.net_noncomm,
            cot_z = EXCLUDED.cot_z,
            sentiment = EXCLUDED.sentiment,
            signal_flag = EXCLUDED.signal_flag,
            updated_at = NOW();
    """)


def build_all():
    print("→ Building gold layer…")
    build_daily_ohlcv()
    build_vix_regime()
    build_macro_flags()
    build_funding_metrics()
    build_cot_sentiment()
    build_regime_features()
    build_hmm_regime()
    build_regime_label()
    print("✅ Gold layer build complete")

def build_regime_features():
    """Goal 2: Compute regime features (ADX14, Hurst, RV5d, etc.)"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_regime_features",
        os.path.join(os.path.dirname(__file__), "build_regime_features.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load build_regime_features module spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.compute_features()

def build_hmm_regime():
    """Goal 3: Train HMM regime model.
    Note: regime/ moved to agents/signals/regime/ on 2026-06-22. The path
    below crosses the etl→signals boundary because HMM training reads
    gold-layer features and writes back to gold — it's data-engineering
    work that happens to live with the signal agent for code locality."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("train_hmm",
        os.path.join(os.path.dirname(__file__), "..", "..", "signals", "regime", "train_hmm.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load train_hmm module spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.train_hmm()

def build_regime_label():
    """Goal 4: Build regime label with rule overrides.
    Note: regime/ moved to agents/signals/regime/ on 2026-06-22."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("regime_rules",
        os.path.join(os.path.dirname(__file__), "..", "..", "signals", "regime", "regime_rules.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("Failed to load regime_rules module spec")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.build_regime_label()


if __name__ == "__main__":
    build_all()
    if _n_stage_failures:
        print(f"\n⚠️  gold_builder: {_n_stage_failures} stage(s) failed: {_failed_stages}")
        sys.exit(_n_stage_failures)
    print("\n✅ gold_builder: all stages OK")
