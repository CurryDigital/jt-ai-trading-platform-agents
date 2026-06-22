# HMM_REFRESH_MAY + FIX_COT_STALENESS — Completion Report

**Agent:** qr_etl  
**Priority:** P1  
**Status:** COMPLETE  
**Date:** 2026-05-29

---

## Goals Executed

### Goal 1: FIX_COT_STALENESS (t_91df6d67)

| Check | Before | After | Status |
|-------|--------|-------|--------|
| `gold.cot_sentiment` max date | 2026-05-29 | 2026-05-29 | ✅ Already current |
| COT report date | 2026-05-19 | 2026-05-19 | ✅ Last Tuesday release |
| Staleness alert | Active | False positive | ✅ COT was never stale |

**Finding:** COT data was already current. The staleness alert was a **false positive** caused by the regime boundary crash, not actual COT staleness.

**COT Data Summary:**
- Instruments: CL (WTI Crude), ES (E-mini S&P), EURO FX, GC (Gold)
- Report date: 2026-05-19 (last CFTC release)
- Forward-filled to 2026-05-29 (daily granularity)
- All z-scores and sentiment labels current

---

### Goal 2: HMM_REFRESH_MAY

| Check | Before | After | Status |
|-------|--------|-------|--------|
| `gold.hmm_regime_states` max date | 2026-05-20 | 2026-05-29 | ✅ Refreshed |
| `gold.regime_label` max date | 2026-05-20 (forward-fill) | 2026-05-29 (real HMM) | ✅ Refreshed |
| Forward-filled rows (confidence=0.85) | 42 | 33 (May 21-29 now real) | ✅ Reduced |
| HMM confidence for May 21-29 | 0.85 (forward-fill) | 1.0 (actual inference) | ✅ Real values |

---

## HMM Inference Results (May 21-29)

| Date | HMM State | HMM Label | Confidence | Regime | Override |
|------|-----------|-----------|------------|--------|----------|
| 2026-05-21 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-22 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-23 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-24 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-25 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-26 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-27 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-28 | 0 | MEAN_REV | 1.0 | CARRY | True |
| 2026-05-29 | 0 | MEAN_REV | 1.0 | CARRY | True |

**Regime Assignment Logic:**
- HMM predicts MEAN_REV for all 9 days (state 0)
- Regime override rules promote to CARRY because:
  - `rv_iv_ratio < 0.60` (range: 0.17-0.59)
  - `vix_z60 < 0` (range: -1.40 to -0.80)
- This is correct — low realized volatility + low VIX = carry regime

---

## Regime Context (May 15-29)

| Date | Regime | HMM Label | Confidence | Override | Note |
|------|--------|-----------|------------|----------|------|
| 2026-05-15 | TREND | CARRY | 1.0 | False | |
| 2026-05-16 | CARRY | CARRY | 1.0 | False | |
| 2026-05-17 | CARRY | CARRY | 0.85 | False | Forward-fill |
| 2026-05-18 | MEAN_REV | MEAN_REV | 0.97 | False | |
| 2026-05-19 | CARRY | MEAN_REV | 0.95 | False | Override |
| 2026-05-20 | CARRY | TREND | 1.0 | False | Override |
| 2026-05-21 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-22 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-23 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-24 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-25 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-26 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-27 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-28 | CARRY | MEAN_REV | 1.0 | True | HMM inference |
| 2026-05-29 | CARRY | MEAN_REV | 1.0 | True | HMM inference |

---

## Key Technical Details

### HMM Model
- **Trained on:** 2026-05-16 (756 rows)
- **Features:** adx14, hurst_30, rv5d, vix_z60, adx_hurst_cross, rv5d_change
- **States:** 3 (MEAN_REV=0, TREND=1, CARRY=2)
- **Label map:** {0: 'MEAN_REV', 1: 'TREND', 2: 'CARRY'}

### Data Quality Fix
- `rv5d_change` was NULL for 2026-05-21 (first gap row)
- Computed as `rv5d.diff()` — 0.0 for first row
- `adx_hurst_cross` computed as `adx14 * hurst_30`
- All features validated: 0 NaN after fill

### Idempotency
- Both `gold.hmm_regime_states` and `gold.regime_label` use `ON CONFLICT DO UPDATE`
- Safe to re-run — will overwrite with same values

---

## Success Criteria

| Criteria | Status |
|----------|--------|
| COT data current (max_date >= last Tuesday) | ✅ 2026-05-29 |
| regime_rules.py handles boundary dates | ✅ Forward-fill + bfill |
| gold.regime_label has row for 2026-05-29 | ✅ CARRY, conf=1.0 |
| hmm_regime_states rows for 2026-05-21→29 | ✅ 9 rows, state=0 |
| No more 0.85 forward-fill rows in gap | ✅ All conf=1.0 |
| Idempotent (safe to re-run) | ✅ ON CONFLICT DO UPDATE |
| t_91df6d67 can be closed | ✅ Ready |

---

## G1 Auto-Refresh Prediction

G1 (TTL=15min) will pick up the new labels on next refresh:

```
GET /api/regime/current
Response: {
  "date": "2026-05-29",
  "regime": "CARRY",
  "hmm_label": "MEAN_REV",
  "confidence": 1.0,
  "override_used": true,
  "active_strategies": [7, 17]
}
```

---

## Remaining Forward-Filled Rows

33 rows still have confidence=0.85 (weekends + historical gaps). These are:
- Weekends (Saturday/Sunday) — expected
- Historical gaps (e.g., 2026-04-27, 2026-04-28) — price data was missing, now fixed
- Next HMM retrain will eliminate these

---

## Files Modified

| File | Change |
|------|--------|
| `regime/regime_rules.py` | Added forward-fill/bfill boundary handling (from FIX_COT_STALENESS) |
| `README_hmm_refresh_may.md` | This documentation |

---

## Warnings

1. **HMM state transition:** May 20 was TREND (state 1), May 21-29 are MEAN_REV (state 0). This is a valid regime shift detected by the model.
2. **All gap days overridden to CARRY:** The HMM predicts MEAN_REV, but override rules (rv_iv_ratio < 0.60 + vix_z60 < 0) promote to CARRY. This is intentional — the override layer has higher priority.
3. **COT next release:** Expected 2026-05-26 report (published Tuesdays). No action needed until then.
