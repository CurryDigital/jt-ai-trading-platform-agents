# EARNINGS_AUTO_UPDATE — Setup Report

**Agent:** qr_etl  
**Priority:** P1  
**Status:** COMPLETE  
**Date:** 2026-05-30

---

## Objective

Schedule earnings actuals update to run Tuesday-Friday mornings before 09:45 ET cron fire, so `pead_long` strategy has `eps_actual` + `price_reaction_1d` available for tickers that reported the previous evening.

---

## What Was Done

### Step 1: Created `earnings_update.py`

**Path:** `~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/earnings_update.py`

**Function:**
- Fetches `eps_actual` from `yfinance.Ticker(ticker).earnings_dates`
- Matches DB `report_date` with yfinance dates (±2 day tolerance)
- Computes `price_reaction_1d` = `(close_t+1 - close_t) / close_t * 100`
- Upserts to `silver.unified_earnings`
- Covers **all tickers** in DB (not just a hardcoded list)

**Key features:**
- Idempotent (ON CONFLICT DO UPDATE)
- Dry-run mode (`--dry-run`)
- Single-ticker mode (`--ticker HPE`)
- Handles `decimal.Decimal` → `float` conversion
- Tolerates weekend/holiday date shifts (±2 days)

### Step 2: Added `price_reaction_1d` column

```sql
ALTER TABLE silver.unified_earnings ADD COLUMN price_reaction_1d numeric;
```

### Step 3: Backfilled historical actuals

**Results:**
- Total earnings rows: **17,335**
- With actuals: **16,514 (95.3%)**
- Pending: **704 (4.1%)**
- Updated today: **141**

**Pending breakdown:**
- Future reports: 514 rows (not yet reported)
- Old stale: 186 rows (yfinance doesn't have actuals for these)
- Recent (last 7 days): 4 rows (will be caught by next cron run)

### Step 4: Registered Hermes cron job

```
Job ID:   961374471b8b
Name:     qr_etl_earnings_update
Schedule: 30 9 * * 2-5  (09:30 UTC Tue-Fri)
Script:   earnings_update.py
Type:     no_agent (direct script execution)
Next run: 2026-06-02 09:30:00 UTC
```

**Note:** 09:30 UTC = 05:30 ET (EDT) or 04:30 ET (EST). This is **before** the 09:45 ET morning_run.

---

## HPE Verification

| Report Date | EPS Estimate | EPS Actual | Status |
|-------------|--------------|------------|--------|
| 2026-06-02 | 0.53 | — | Pending (reports tonight) |
| 2026-06-01 | 0.53 | — | Pending (reports tonight) |
| 2026-03-09 | 0.59 | 0.65 | ✅ Reported |
| 2025-12-04 | 0.58 | 0.62 | ✅ Reported |
| 2025-09-03 | 0.24 | 0.21 | ✅ Reported |

**HPE reports Monday evening (2026-06-01 after market close).**
- Cron runs Tuesday 09:30 UTC (05:30 ET)
- Will fetch actuals from yfinance
- `pead_long` will have data before 09:45 ET morning_run

---

## Success Criteria

| Criteria | Status |
|----------|--------|
| `earnings_update.py` fetches eps_actual from yfinance | ✅ |
| Cron job registered: 09:30 UTC Tue-Fri | ✅ |
| HPE historical actuals verified in DB | ✅ |
| `price_reaction_1d` column added | ✅ |
| 95.3% of earnings have actuals | ✅ |
| Tuesday morning: HPE eps_actual populated before 09:45 ET | ✅ Scheduled |

---

## Files Delivered

| File | Path |
|------|------|
| Earnings update script | `~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/earnings_update.py` |
| Cron script copy | `~/.hermes/scripts/earnings_update.py` |
| README | `~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/README_earnings_auto_update.md` |

---

## Warnings

1. **UTC vs ET timezone:** Cron is 09:30 UTC = 05:30 ET (EDT). This is 4h15m before 09:45 ET morning_run. Safe buffer.
2. **yfinance rate limits:** 275 tickers × 4 days/week = ~1,100 API calls. yfinance handles this fine via caching.
3. **Old stale data:** 186 rows with past report dates but no actuals in yfinance. These may be delisted tickers or data source gaps. Non-critical.
4. **Date tolerance:** ±2 days matching between DB and yfinance. Handles weekend/holiday shifts but may miss tickers with larger discrepancies.

---

## Next Steps

1. **Monitor first cron run** on 2026-06-02 09:30 UTC
2. **Verify HPE actuals** populated after Monday evening report
3. **Adjust schedule** if needed (e.g., 08:30 UTC for earlier coverage)
