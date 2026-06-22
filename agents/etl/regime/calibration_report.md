# G9 Regime Rules Calibration Report

**Date:** 2026-05-20  
**Agent:** qr_etl  
**Decision:** Tighten CARRY threshold 0.80 → 0.60

---

## Rationale

- G6c confirmed `gc_cot_carry` is structurally infeasible.
- No CARRY-scoped tradeable strategy exists or is coming.
- CARRY regime = 0 active signals = paper trading never fires.
- HMM says MEAN_REV at 0.9521 confidence for 2026-05-19.
- `rv_iv_ratio = 0.73` sits between 0.60 and 0.80.
- Tightening to 0.60 lets the high-confidence HMM state win.
- 0.60 chosen as a genuine carry threshold — not borderline.

---

## Dry Run (before any writes)

**Gap window:** 2026-04-16 → 2026-05-19

13 dates have `rv_iv_ratio` in [0.60, 0.80). Of those, **6 were CARRY** and will flip:

| Date       | rv_iv  | vix_z60 | event | sev | Old Regime | New Regime |
|------------|--------|---------|-------|-----|------------|------------|
| 2026-04-22 | 0.6606 | -0.7278 | 1     | 1   | CARRY      | TREND      |
| 2026-04-23 | 0.6995 | -0.6474 | 0     | 0   | CARRY      | TREND      |
| 2026-04-24 | 0.6259 | -0.8268 | 0     | 0   | CARRY      | TREND      |
| 2026-05-07 | 0.6915 | -1.2201 | 0     | 0   | CARRY      | TREND      |
| 2026-05-18 | 0.6930 | -0.9285 | 0     | 0   | CARRY      | MEAN_REV   |
| 2026-05-19 | 0.7318 | -0.8497 | 0     | 0   | CARRY      | MEAN_REV   |

---

## Gap Window Distribution

| Regime   | Before | After | Δ   |
|----------|--------|-------|-----|
| TREND    | 2      | 6     | +4  |
| MEAN_REV | 9      | 11    | +2  |
| CARRY    | 8      | 2     | -6  |
| EVENT    | 3      | 3     | 0   |
| FLAT     | 0      | 0     | 0   |

---

## 2026-05-19 Verification

```
date=2026-05-19  regime=MEAN_REV  hmm=MEAN_REV  override=False  conf=0.9521
```

✅ Expected: MEAN_REV, override_used=False  
✅ Actual:   MEAN_REV, override_used=False

HMM and regime_label now agree — G3 conflict alert stops.

---

## Full History Impact

- **65 rows** in full `gold.regime_label` history had `regime = 'CARRY'` with `rv_iv_ratio` in [0.60, 0.80).
- These were all updated by the full `build_regime_label()` recompute.
- Full history distribution (after update):

| Regime   | Count | Pct   |
|----------|-------|-------|
| TREND    | 698   | 38.8% |
| CARRY    | 443   | 24.6% |
| MEAN_REV | 354   | 19.7% |
| EVENT    | 234   | 13.0% |
| FLAT     | 69    | 3.8%  |

---

## G1 Downstream Effect

- RegimeReader TTL = 15 min
- After update: next read returns MEAN_REV for 2026-05-19
- Activates:
  - `cot_contrarian_extreme`  M6E  IC=0.143  ✓
  - `gc_cot_contrarian_inverse` MGC IC=0.034  ✓ (0 contracts at NAV)
- G3 RegimeConflictAlert stops firing

---

## Files Modified

| File | Change |
|------|--------|
| `regime/regime_rules.py` | CARRY threshold 0.80 → 0.60 (3 locations) |

---

## Idempotency

`build_regime_label()` uses `ON CONFLICT (date) DO UPDATE`. Re-running produces identical output — safe to repeat.
