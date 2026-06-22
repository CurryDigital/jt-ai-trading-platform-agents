#!/usr/bin/env python3
"""
Regime Rules Engine — Goal 4
============================
Combine HMM output with rule-override layer to produce
one clean regime label per trading day.

Export:
    assign_regime(row: pd.Series) -> str
    build_regime_label(conn) -> pd.DataFrame
    get_active_strategies(conn) -> dict
"""
import sys, os
sys.path.insert(0, 'shared/scripts')
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection
from datetime import date

import numpy as np
import pandas as pd


# ── Strategy Router ───────────────────────────────────────────────────────────

STRATEGY_MAP = {
    'TREND'   : [1, 2, 6, 11, 15, 16, 18],
    'MEAN_REV': [3, 5, 8, 10, 13, 14, 19, 20],
    'CARRY'   : [7, 17],
    'EVENT'   : [4, 12],
    'FLAT'    : []
}

VALID_REGIMES = {'TREND', 'MEAN_REV', 'CARRY', 'EVENT', 'FLAT'}


# ── Public API ────────────────────────────────────────────────────────────────

def assign_regime(row: pd.Series) -> str:
    """
    Apply rule-override logic in strict priority order.
    First match wins. Falls back to HMM label if no rule matches.
    
    Two-tier event handling:
      - severity >= 2 (FOMC, CPI, NFP) → EVENT regime
      - severity = 1 (EIA) → fall through to normal rules
    """
    # Priority 1 — EVENT (high-severity only: FOMC, CPI, NFP)
    if row.get('event_flag') == 1 and row.get('severity', 0) >= 2:
        return 'EVENT'

    # Priority 2 — FLAT
    if row.get('vix_z60') is not None and row['vix_z60'] > 2.5:
        return 'FLAT'

    # Priority 3 — TREND
    if (row.get('adx14') is not None and row['adx14'] > 22 and
        row.get('hurst_30') is not None and row['hurst_30'] > 0.55 and
        row.get('rv5d_change') is not None and row['rv5d_change'] > 0):
        return 'TREND'

    # Priority 4 — MEAN_REV
    if (row.get('adx14') is not None and row['adx14'] < 22 and
        row.get('rv5d_change') is not None and row['rv5d_change'] < 0 and
        row.get('vix_z60') is not None and row['vix_z60'] < 0.5):
        return 'MEAN_REV'

    # Priority 5 — CARRY
    if (row.get('rv_iv_ratio') is not None and row['rv_iv_ratio'] < 0.60 and
        row.get('vix_z60') is not None and row['vix_z60'] < 0):
        return 'CARRY'

    # Priority 6 — HMM fallback
    hmm = row.get('hmm_label')
    if hmm in VALID_REGIMES:
        return hmm
    return 'CARRY'  # ultimate safety net


def build_regime_label(conn=None) -> pd.DataFrame:
    """
    Build gold.regime_label by joining gold.hmm_regime_states
    with gold.regime_features and applying assign_regime().
    
    Boundary handling: forward-fills HMM states for dates where
    regime_features exists but hmm_regime_states does not (gaps
    up to 5 business days).  Confidence discounted to 0.85 for
    forward-filled rows.  Gaps > 5 days emit a WARN log.
    """
    if conn is None:
        conn = get_connection()
    cur = conn.cursor()

    # ── 1. Load HMM states ────────────────────────────────────────────────────
    cur.execute("""
        SELECT date, hmm_state, hmm_label, confidence
        FROM gold.hmm_regime_states
        ORDER BY date
    """)
    hmm_rows = cur.fetchall()
    if not hmm_rows:
        raise ValueError("No data found in gold.hmm_regime_states")

    hmm = pd.DataFrame(hmm_rows, columns=['date', 'hmm_state', 'hmm_label', 'confidence'])
    hmm['date'] = pd.to_datetime(hmm['date'])
    hmm = hmm.set_index('date').sort_index()

    # ── 2. Load regime features (need rule columns + severity) ──────────────────
    cur.execute("""
        SELECT r.date, r.adx14, r.hurst_30, r.rv5d, r.rv_iv_ratio, r.vix_z60,
               r.event_flag, r.rv5d_change,
               CASE m.severity
                   WHEN 'heavy' THEN 3
                   WHEN 'medium' THEN 2
                   WHEN 'light' THEN 1
                   ELSE 0
               END as severity
        FROM gold.regime_features r
        LEFT JOIN gold.macro_event_flags m ON r.date = m.date
        ORDER BY r.date
    """)
    feat_rows = cur.fetchall()
    feat = pd.DataFrame(feat_rows, columns=[
        'date', 'adx14', 'hurst_30', 'rv5d', 'rv_iv_ratio',
        'vix_z60', 'event_flag', 'rv5d_change', 'severity'
    ])
    feat['date'] = pd.to_datetime(feat['date'])
    feat = feat.set_index('date').sort_index()

    # Cast Decimal to float
    for col in feat.columns:
        feat[col] = feat[col].astype(float)

    # ── 3. Join ───────────────────────────────────────────────────────────────
    # Forward-fill HMM states for ALL gaps (weekends, holidays, stale data)
    # Reindex HMM to match feat dates, forward filling
    hmm_extended = hmm.reindex(feat.index, method='ffill')
    # For dates before first HMM state, backward fill
    hmm_extended = hmm_extended.bfill()
    
    # Discount confidence for forward-filled dates
    original_hmm_dates = set(hmm.index)
    for idx in hmm_extended.index:
        if idx not in original_hmm_dates:
            hmm_extended.loc[idx, 'confidence'] = 0.85
    
    df = hmm_extended.join(feat, how='inner')
    if df.empty:
        raise ValueError("Join between hmm_regime_states and regime_features returned no rows")
    
    # Check for gaps > 5 business days at the tail
    last_hmm_date = hmm.index.max()
    extra_dates = feat.index[feat.index > last_hmm_date]
    if len(extra_dates) > 5:
        print(f"🚨 WARN: HMM gap > 5 business days ({len(extra_dates)} days). DataStalenessAlert should fire.")
    elif len(extra_dates) > 0:
        print(f"⚠️  HMM forward-fill: {len(extra_dates)} dates beyond last HMM state ({last_hmm_date.date()})")

    # ── 4. Apply regime rules ─────────────────────────────────────────────────
    df['regime'] = df.apply(assign_regime, axis=1)
    df['override_used'] = (
        (df['event_flag'] == 1) |
        (df['vix_z60'] > 2.5) |
        (
            (df['adx14'] > 22) & (df['hurst_30'] > 0.55) & (df['rv5d_change'] > 0)
        ) |
        (
            (df['adx14'] < 22) & (df['rv5d_change'] < 0) & (df['vix_z60'] < 0.5)
        ) |
        (
            (df['rv_iv_ratio'] < 0.60) & (df['vix_z60'] < 0)
        )
    )

    # ── 5. Validation ─────────────────────────────────────────────────────────
    _validate(df)

    # ── 6. Upsert to gold.regime_label ────────────────────────────────────────
    _ensure_table(conn)
    inserted = 0
    for idx, row in df.reset_index().iterrows():
        cur.execute("""
            INSERT INTO gold.regime_label
                (date, regime, hmm_label, override_used, confidence, severity, computed_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (date) DO UPDATE SET
                regime = EXCLUDED.regime,
                hmm_label = EXCLUDED.hmm_label,
                override_used = EXCLUDED.override_used,
                confidence = EXCLUDED.confidence,
                severity = EXCLUDED.severity,
                computed_at = NOW()
        """, (
            row['date'], row['regime'], row['hmm_label'],
            bool(row['override_used']), float(row['confidence']),
            int(row['severity']) if pd.notna(row['severity']) else 0
        ))
        inserted += 1
    conn.commit()
    print(f"✅ gold.regime_label — {inserted} rows upserted")

    # ── 7. Override analysis ──────────────────────────────────────────────────
    _print_override_analysis(df)

    # ── 8. Historical spot checks ─────────────────────────────────────────────
    _spot_checks(df)

    # ── 9. Today's active strategies ──────────────────────────────────────────
    today_info = get_active_strategies(conn)
    print(f"\n=== Today's Active Strategies ===")
    print(f"  Date: {today_info['date']}")
    print(f"  Regime: {today_info['regime']}")
    print(f"  Active strategies: {today_info['active_strategies']}")
    print(f"  Override used: {today_info['override_used']}")
    print(f"  Confidence: {today_info['confidence']:.4f}")
    if today_info.get('eia_day'):
        print(f"  EIA day: True (strategy 12 added)")

    conn.close()
    return df


def get_active_strategies(conn=None) -> dict:
    """
    Reads today's regime from gold.regime_label.
    Returns dict with date, regime, active_strategies, override_used, confidence.
    On EIA days (severity=1), adds strategy 12 to the active list.
    """
    if conn is None:
        conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT date, regime, override_used, confidence, severity
        FROM gold.regime_label
        ORDER BY date DESC
        LIMIT 1
    """)
    row = cur.fetchone()
    if not row:
        raise ValueError("No data found in gold.regime_label")
    date_val, regime, override_used, confidence, severity = row
    
    active = STRATEGY_MAP.get(regime, []).copy()
    eia_day = False
    
    # Add strategy 12 on EIA days (severity=1) regardless of regime
    if severity == 1:
        if 12 not in active:
            active.append(12)
        eia_day = True
    
    conn.close()
    return {
        "date": str(date_val),
        "regime": regime,
        "active_strategies": sorted(active),
        "override_used": bool(override_used),
        "confidence": float(confidence) if confidence is not None else 0.0,
        "eia_day": eia_day,
    }


# ── Internal helpers ──────────────────────────────────────────────────────────

def _ensure_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS gold.regime_label (
            date          DATE PRIMARY KEY,
            regime        VARCHAR(10),
            hmm_label     VARCHAR(10),
            override_used BOOLEAN,
            confidence    FLOAT,
            computed_at   TIMESTAMP DEFAULT now()
        )
    """)
    conn.commit()


def _validate(df: pd.DataFrame):
    last252 = df.tail(252)

    # 1. Zero NULLs in regime for last 252 rows
    if last252['regime'].isna().any():
        raise ValueError("Validation fail: NULL values in regime column within last 252 rows")

    # 2. Only valid regime values
    invalid = set(last252['regime'].unique()) - VALID_REGIMES
    if invalid:
        raise ValueError(f"Validation fail: invalid regime values found: {invalid}")

    # 3. Each regime fires on at least 0.5% of all days (EVENT is rare)
    counts = df['regime'].value_counts()
    n_total = len(df)
    for regime in VALID_REGIMES:
        pct = counts.get(regime, 0) / n_total * 100
        if pct < 0.5:
            raise ValueError(f"Validation fail: regime '{regime}' fires on only {pct:.1f}% of days (min 0.5%)")

    # 4. FLAT fires correctly: all days with vix_z60 > 2.5 must be FLAT
    # (except EVENT days which have priority 1)
    flat_check = df[(df['vix_z60'] > 2.5) & (df['event_flag'] != 1)]
    if not flat_check.empty and not (flat_check['regime'] == 'FLAT').all():
        offenders = flat_check[flat_check['regime'] != 'FLAT']
        raise ValueError(f"Validation fail: {len(offenders)} days with vix_z60 > 2.5 (and not EVENT) are not FLAT")

    # 5. EVENT fires correctly: all days with event_flag == 1 AND severity >= 2 must be EVENT
    event_check = df[(df['event_flag'] == 1) & (df['severity'] >= 2)]
    if not event_check.empty and not (event_check['regime'] == 'EVENT').all():
        offenders = event_check[event_check['regime'] != 'EVENT']
        raise ValueError(f"Validation fail: {len(offenders)} high-severity event days are not EVENT")

    # 5b. EIA days (severity=1) should NOT be EVENT
    eia_check = df[(df['event_flag'] == 1) & (df['severity'] == 1)]
    if not eia_check.empty and (eia_check['regime'] == 'EVENT').any():
        offenders = eia_check[eia_check['regime'] == 'EVENT']
        raise ValueError(f"Validation fail: {len(offenders)} EIA days incorrectly labeled as EVENT")

    # 6. override_used = True for all FLAT and EVENT rows
    flat_event = df[df['regime'].isin(['FLAT', 'EVENT'])]
    if not flat_event.empty and not flat_event['override_used'].all():
        offenders = flat_event[~flat_event['override_used']]
        raise ValueError(f"Validation fail: {len(offenders)} FLAT/EVENT rows have override_used=False")

    print("✅ All validations passed")


def _print_override_analysis(df: pd.DataFrame):
    n_total = len(df)
    counts = df['regime'].value_counts()

    print("\n=== Regime Distribution (full history) ===")
    for regime in ['TREND', 'MEAN_REV', 'CARRY', 'EVENT', 'FLAT']:
        c = counts.get(regime, 0)
        pct = c / n_total * 100 if n_total else 0
        print(f"  {regime:8s}: {c:5d} days ({pct:5.1f}%)")

    override_true = df['override_used'].sum()
    override_false = n_total - override_true
    print(f"\n=== Override Usage ===")
    print(f"  Rule-driven (override_used=True):   {override_true:5d} days ({override_true/n_total*100:.1f}%)")
    print(f"  HMM fallback (override_used=False): {override_false:5d} days ({override_false/n_total*100:.1f}%)")

    print(f"\n=== Override Breakdown by Regime ===")
    flat_by_rule = len(df[(df['regime'] == 'FLAT') & (df['vix_z60'] > 2.5)])
    event_by_rule = len(df[(df['regime'] == 'EVENT') & (df['severity'] >= 2)])
    trend_by_rule = len(df[(df['regime'] == 'TREND') & (
        (df['adx14'] > 22) & (df['hurst_30'] > 0.55) & (df['rv5d_change'] > 0)
    )])
    meanrev_by_rule = len(df[(df['regime'] == 'MEAN_REV') & (
        (df['adx14'] < 22) & (df['rv5d_change'] < 0) & (df['vix_z60'] < 0.5)
    )])
    carry_by_rule = len(df[(df['regime'] == 'CARRY') & (
        (df['rv_iv_ratio'] < 0.60) & (df['vix_z60'] < 0)
    )])
    print(f"  FLAT triggered by vix_z60 > 2.5:     {flat_by_rule:5d} days")
    print(f"  EVENT triggered by event_flag=1:     {event_by_rule:5d} days")
    print(f"  TREND triggered by rule:             {trend_by_rule:5d} days")
    print(f"  MEAN_REV triggered by rule:          {meanrev_by_rule:5d} days")
    print(f"  CARRY triggered by rule:             {carry_by_rule:5d} days")


def _spot_checks(df: pd.DataFrame):
    checks = {
        '2020-03-16': 'FLAT or TREND (peak crash panic)',
        '2020-11-09': 'TREND (vaccine Monday +4%)',
        '2022-06-13': 'FLAT or TREND (bear market)',
        '2023-10-27': 'TREND or MEAN_REV (rally day)',
        '2024-07-11': 'EVENT (CPI release day)',
    }
    print("\n=== Historical Spot Checks ===")
    for d, expected in checks.items():
        ts = pd.Timestamp(d)
        if ts in df.index:
            row = df.loc[ts]
            regime = row['regime']
            hmm = row['hmm_label']
            override = row['override_used']
            vix = row['vix_z60']
            event = row['event_flag']
            plausible = '✅' if _is_plausible(regime, expected) else '⚠️ FLAG'
            print(f"  {d} → {regime:8s} (HMM={hmm}, override={override}, vix_z60={vix:.2f}, event={int(event)})  {plausible}")
            print(f"         Expected: {expected}")
        else:
            print(f"  {d} → NOT IN DATASET")


def _is_plausible(actual: str, expected: str) -> bool:
    """Simple plausibility check against expected description."""
    expected_upper = expected.upper()
    if actual in expected_upper:
        return True
    if 'FLAT OR TREND' in expected_upper and actual in ('FLAT', 'TREND'):
        return True
    if 'TREND OR MEAN_REV' in expected_upper and actual in ('TREND', 'MEAN_REV'):
        return True
    return False


# ── Main (standalone) ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("→ Building regime labels...")
    build_regime_label()
    print("✅ Regime labels complete")
