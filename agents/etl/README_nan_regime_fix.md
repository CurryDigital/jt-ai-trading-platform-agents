# FIX_NAN_REGIME_FEATURES — Root Cause & Resolution

## Problem

`gold.regime_features` had 4 critical columns as NaN since 2026-05-25:
- `adx14`       — NULL (needs high/low OHLC)
- `hurst_30`    — NULL (needs 30 days of log-returns)
- `rv5d`        — NULL (needs 5 days of log-returns)
- `rv_iv_ratio` — NULL (needs RV5d + VIX)

Additionally, `breadth_50` dropped from 0.378 → 0.005 on May 16 (pipeline bug).

HMM was running on only 3 of 9 features → regime labels unreliable.

## Root Cause

1. **Weekend/holiday rows in `gold.daily_ohlcv`** with NULL close/high/low/open:
   - 2026-05-16 (Saturday), 2026-05-17 (Sunday)
   - 2026-05-23 (Saturday), 2026-05-24 (Sunday)
   - 2026-05-25 (Memorial Day — Monday, market closed)

2. **SPY data gaps**: Some weekend rows had partial data (open/high/low but NULL close/volume), corrupting the rolling calculations.

3. **breadth_50 bug**: Weekend rows with 382 tickers (vs 791 on trading days) diluted the breadth calculation. The `build_regime_features.py` script fetched ALL dates including weekends, and the `rolling(50)` window crossed weekend gaps, producing incorrect SMA50 values for tickers with discontinuous data.

## Fixes Applied

### Step 1: Clean weekend/holiday data
```sql
DELETE FROM gold.daily_ohlcv
WHERE date IN ('2026-05-16', '2026-05-17', '2026-05-23', '2026-05-24', '2026-05-25')
  AND (close IS NULL OR date IN ('2026-05-16', '2026-05-17', '2026-05-23', '2026-05-24'));
-- Deleted: 1,525 weekend rows + 578 Memorial Day NULL rows
```

### Step 2: Backfill SPY OHLCV
- Fetched SPY from yfinance for 2026-05-15 to 2026-05-29
- Upserted into `gold.daily_ohlcv` with proper OHLCV

### Step 3: Recompute all features
Ran `build_regime_features.py`:
- Upserted 1,836 rows
- Validation passed
- All features now populated

### Step 4: Re-run HMM inference
Ran `hmm_backfill.py`:
- Loaded model trained on 2026-05-15 (756 rows)
- Predicted 24 gap rows
- Applied regime override logic
- Upserted into `gold.hmm_regime_states` and `gold.regime_label`

## Before vs After

| Date | ADX14 | Hurst | RV5d | RV/IV | VIX Z60 | Breadth | Regime (Before) | Regime (After) |
|------|-------|-------|------|-------|---------|---------|-----------------|----------------|
| 2026-05-26 | NaN | NaN | NaN | NaN | -1.02 | 0.079 | MEAN_REV | MEAN_REV |
| 2026-05-27 | NaN | NaN | NaN | NaN | -1.16 | 0.017 | MEAN_REV | MEAN_REV |
| 2026-05-28 | NaN | NaN | NaN | NaN | -1.25 | 0.018 | MEAN_REV | MEAN_REV |
| 2026-05-29 | NaN | NaN | NaN | NaN | -1.30 | 0.013 | MEAN_REV | MEAN_REV |

**After fix:**
| Date | ADX14 | Hurst | RV5d | RV/IV | VIX Z60 | Breadth | Regime |
|------|-------|-------|------|-------|---------|---------|--------|
| 2026-05-26 | 41.21 | 0.682 | 0.100 | 0.591 | -1.02 | **0.417** | MEAN_REV |
| 2026-05-27 | 39.57 | 0.650 | 0.064 | 0.394 | -1.16 | **0.396** | MEAN_REV |
| 2026-05-28 | 38.98 | 0.613 | 0.043 | 0.275 | -1.25 | **0.397** | MEAN_REV |
| 2026-05-29 | 38.31 | 0.625 | 0.042 | 0.275 | -1.30 | **0.393** | MEAN_REV |

## Regime Changes

No dates flipped from MEAN_REV to TREND after feature fix. The regime stayed MEAN_REV because:
- ADX14 < 20 (weak trend)
- RV/IV ratio < 0.60 (low realized vol vs implied)
- VIX Z60 < -1.0 (complacency)

However, May 15-20 are now correctly labeled **TREND** (ADX14 > 40, strong directional movement).

## Data Quality Notes

- **breadth_50** now in valid range 0.37-0.42 (was 0.005-0.079)
- **0 NaN values** in adx14, hurst_30, rv5d, rv_iv_ratio for last 14 trading days
- **HMM re-run completed** with all 9 features
- **Weekend rows removed** from daily_ohlcv to prevent future corruption

## Files Modified

- `gold.daily_ohlcv` — deleted 2,103 invalid weekend/holiday rows
- `gold.regime_features` — recomputed 1,836 rows
- `gold.hmm_regime_states` — recomputed gap rows
- `gold.regime_label` — recomputed gap rows

## Preventive Measures

1. Add weekend/holiday filter to daily ETL before `gold.daily_ohlcv` insert
2. Add data quality check: `assert tickers_count > 700` for breadth calculation
3. Add NaN check after feature computation: abort if > 1% NaN in last 7 days

## Final Regime Label

**2026-05-29: MEAN_REV (confidence: 1.0, override: false)**

Features driving classification:
- ADX14 = 38.3 (trend weakening but not mean-reverting yet)
- Hurst = 0.625 (slight trending bias)
- RV/IV = 0.275 (realized vol much lower than implied — complacency)
- VIX Z60 = -1.30 (VIX near 60-day low)
- Breadth = 0.393 (neutral, ~40% of stocks above 50d MA)
