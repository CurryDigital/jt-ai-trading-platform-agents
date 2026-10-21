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
    # asset_class / market provenance (2026-08-24, kanban t_ac502e22):
    # This stage is a pure passthrough — it NEVER stamps asset_class/market
    # itself. Values come verbatim from silver.unified_prices, which is stamped
    # by silver/clean_unified_prices.py via LEFT JOIN silver.asset_registry
    # (master: gold.asset_registry). The asset registry is the SINGLE SOURCE
    # OF TRUTH for asset_class/market; do not hardcode class strings here.
    #
    # Window caveat: only the last 14 days are re-copied from silver each run.
    # Rows older than 14 days are NEVER restamped by this builder, so
    # historical rows written by pre-registry-era builders retain legacy
    # lowercase/alias values ('equity', 'HK Stock', 'crypto', NULL, ...).
    # Full-history restamp of gold.daily_ohlcv is handled out-of-band by the
    # DB task family under kanban t_4a403ac8 — do not widen this window as a
    # "fix"; the 14-day window is intentional for run cost.
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
          -- Trading-calendar guard (2026-10-15, kanban t_183d8bb1):
          -- yfinance periodically emits weekend/holiday artifact rows
          -- (e.g. 2026-05-16..06-07 weekends, Memorial/Juneteenth 2026)
          -- that corrupt rolling features (regime_features adx14 NaN).
          -- Rule: crypto trades 24/7; FX/futures open Sunday evening UTC;
          -- every other instrument is weekday-only. US-exchange instruments
          -- are additionally blocked on NYSE full-close holidays
          -- (gold.us_market_holidays); HK/CN/SG trade on US holidays and are
          -- not affected.
          AND (asset_class = 'CRYPTO'
               OR EXTRACT(ISODOW FROM date) <= 5
               OR (asset_class IN ('FX', 'COMMODITY') AND EXTRACT(ISODOW FROM date) = 7))
          AND (date NOT IN (SELECT holiday_date FROM gold.us_market_holidays)
               OR asset_class IN ('CRYPTO', 'FX', 'COMMODITY', 'CURRENCY')
               OR (asset_class IN ('STOCK', 'ETF', 'INDEX', 'VOLATILITY') AND market IS DISTINCT FROM 'US')
               OR (asset_class IS NULL
                   AND (ticker ~ '\.(HK|SI|SS|SZ)$' OR ticker LIKE '%-USD'
                        OR ticker LIKE '%=X' OR ticker LIKE '%=F' OR ticker LIKE '^%')))
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
    # 2026-08-19 (kanban t_817e5f40): --stages lets the 22:30 UTC US
    # post-close top-up rebuild only the price-driven gold tables after the
    # evening US-equity ingest, without re-running the HMM/regime stages.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--stages', default=None,
                    help="Comma-separated stage subset: daily_ohlcv, vix_regime, "
                         "macro_flags, funding, cot, regime_features, hmm, regime_label. "
                         "Default: all stages.")
    args = ap.parse_args()
    if args.stages:
        stage_map = {
            'daily_ohlcv': build_daily_ohlcv,
            'vix_regime': build_vix_regime,
            'macro_flags': build_macro_flags,
            'funding': build_funding_metrics,
            'cot': build_cot_sentiment,
            'regime_features': build_regime_features,
            'hmm': build_hmm_regime,
            'regime_label': build_regime_label,
        }
        for name in [s.strip() for s in args.stages.split(',') if s.strip()]:
            fn = stage_map.get(name)
            if fn is None:
                print(f"❌ unknown stage '{name}' — valid: {sorted(stage_map)}")
                sys.exit(2)
            fn()
    else:
        build_all()
    if _n_stage_failures:
        print(f"\n⚠️  gold_builder: {_n_stage_failures} stage(s) failed: {_failed_stages}")
        sys.exit(_n_stage_failures)
    print("\n✅ gold_builder: all stages OK")
