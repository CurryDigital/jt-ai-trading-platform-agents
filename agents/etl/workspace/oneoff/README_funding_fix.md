# G10e_FUNDING_FIX — Binance Perpetual Funding Rate Fix

**Agent:** qr_etl  
**Priority:** P1  
**Status:** COMPLETE  
**Date:** 2026-05-29

---

## Problem

`gold.crypto_funding_metrics.funding_rate_8h` was suspected to be a **volume proxy**, not the actual Binance perpetual funding rate. This was flagged as the biggest robustness risk before promotion to the research pipeline.

## Investigation

### Step 1: Check existing data

```sql
SELECT date, symbol, funding_rate_8h, funding_z, n_obs
FROM gold.crypto_funding_metrics
WHERE symbol = 'BTCUSDT'
ORDER BY date DESC LIMIT 5;
```

**Result BEFORE fix:**

| date       | symbol  | funding_rate_8h | funding_z | n_obs |
|------------|---------|-----------------|-----------|-------|
| 2026-05-20 | BTCUSDT | 0.00005619      | 1.6570    | 2     |
| 2026-05-19 | BTCUSDT | 0.00005179      | 1.6824    | 3     |

- Values were already in the ~0.0001 range (correct magnitude for funding rates)
- But source was unclear — possibly a proxy
- History only went back to 2025-05-14 (~1 year)

### Step 2: Ingest real Binance funding rate

**Source:** `GET https://fapi.binance.com/fapi/v1/fundingRate?symbol=BTCUSDT&limit=1000`

**Response format:**
```json
{
  "symbol": "BTCUSDT",
  "fundingTime": 1779955200000,
  "fundingRate": "0.00005011",
  "markPrice": "73467.37135507"
}
```

**Aggregation:**
- Binance pays funding every 8 hours (00:00, 08:00, 16:00 UTC)
- Daily mean = average of up to 3 funding rates per day
- `n_obs` = number of 8h observations in that day

**Symbols covered:** 11 USDT perpetuals
- BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT
- DOGEUSDT, ADAUSDT, LINKUSDT, DOTUSDT, LTCUSDT, AVAXUSDT
- (MATICUSDT delisted from Binance futures)

**History fetched:**

| Symbol   | Days  | Range                  |
|----------|-------|------------------------|
| BTCUSDT  | 2,454 | 2019-09-10 to 2026-05-29 |
| ETHUSDT  | 2,376 | 2019-11-27 to 2026-05-29 |
| BNBUSDT  | 2,301 | 2020-02-10 to 2026-05-29 |
| XRPUSDT  | 2,336 | 2020-01-06 to 2026-05-29 |
| LTCUSDT  | 2,333 | 2020-01-09 to 2026-05-29 |
| LINKUSDT | 2,325 | 2020-01-17 to 2026-05-29 |
| ADAUSDT  | 2,323 | 2020-01-19 to 2026-05-29 |
| DOGEUSDT | 2,150 | 2020-07-10 to 2026-05-29 |
| DOTUSDT  | 2,109 | 2020-08-20 to 2026-05-29 |
| SOLUSDT  | 2,085 | 2020-09-13 to 2026-05-29 |
| AVAXUSDT | 2,076 | 2020-09-22 to 2026-05-29 |

### Step 3: Z-score recomputation

Methodology (same as G6b):
- Rolling 364-day window
- Minimum 30 days of history before first z-score
- `funding_z = (rate - mean_364d) / stdev_364d`

### Step 4: Upsert to gold.crypto_funding_metrics

Total rows upserted: **24,868**

---

## Result AFTER fix

```sql
SELECT date, symbol, funding_rate_8h, funding_z, n_obs
FROM gold.crypto_funding_metrics
WHERE symbol = 'BTCUSDT'
ORDER BY date DESC LIMIT 5;
```

| date       | symbol  | funding_rate_8h | funding_z | n_obs |
|------------|---------|-----------------|-----------|-------|
| 2026-05-29 | BTCUSDT | 0.00010000      | 1.6085    | 1     |
| 2026-05-28 | BTCUSDT | 0.00008337      | 1.2182    | 3     |
| 2026-05-27 | BTCUSDT | 0.00009621      | 1.5324    | 3     |
| 2026-05-26 | BTCUSDT | 0.00005895      | 0.6435    | 3     |
| 2026-05-25 | BTCUSDT | 0.00003834      | 0.1477    | 3     |

### Verification

```sql
SELECT symbol, COUNT(*) as rows, MIN(date) as earliest, MAX(date) as latest,
       AVG(ABS(funding_rate_8h)) as avg_abs_rate
FROM gold.crypto_funding_metrics
GROUP BY symbol ORDER BY rows DESC;
```

| Symbol   | Rows | Earliest   | Latest     | Avg Abs Rate |
|----------|------|------------|------------|--------------|
| BTCUSDT  | 2454 | 2019-09-10 | 2026-05-29 | 0.000123     |
| ETHUSDT  | 2376 | 2019-11-27 | 2026-05-29 | 0.000147     |
| XRPUSDT  | 2336 | 2020-01-06 | 2026-05-29 | 0.000174     |
| LTCUSDT  | 2333 | 2020-01-09 | 2026-05-29 | 0.000153     |
| LINKUSDT | 2325 | 2020-01-17 | 2026-05-29 | 0.000166     |
| ADAUSDT  | 2323 | 2020-01-19 | 2026-05-29 | 0.000167     |
| BNBUSDT  | 2301 | 2020-02-10 | 2026-05-29 | 0.000177     |
| DOGEUSDT | 2150 | 2020-07-10 | 2026-05-29 | 0.000155     |
| DOTUSDT  | 2109 | 2020-08-20 | 2026-05-29 | 0.000171     |
| SOLUSDT  | 2085 | 2020-09-13 | 2026-05-29 | 0.000187     |
| AVAXUSDT | 2076 | 2020-09-22 | 2026-05-29 | 0.000177     |
| MATICUSDT| 372  | 2025-05-14 | 2026-05-20 | 0.000100     |

✅ **funding_rate_8h values are ~0.0001 to 0.001** (correct for funding rates)  
✅ **NOT large volume numbers**  
✅ **Date range >= 2021-01-01 for all active symbols**  
✅ **History extends back to 2019-09-10 for BTC**

---

## Current Funding Values (BTCUSDT)

| Metric            | Value     |
|-------------------|-----------|
| Current rate      | 0.00010000 |
| Current z-score   | 1.6085    |
| Date              | 2026-05-29 |
| 8h observations   | 1 (partial day) |

---

## Files

| File | Path |
|------|------|
| Ingest script | `~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/funding_rate_fix.py` |
| This README | `~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/README_funding_fix.md` |

---

## Report to qr_research

✅ **Real Binance perpetual funding rate** now in `gold.crypto_funding_metrics`  
✅ **funding_z recomputed** from actual rate (not volume proxy)  
✅ **Date range:** 2019-09-10 to 2026-05-29 for BTC (≥ 2021-01-01 for all)  
✅ **Current BTC funding_rate:** 0.00010000  
✅ **Current BTC funding_z:** 1.6085

**Risk note:** MATICUSDT was delisted from Binance futures. The 372 rows for MATIC are stale (2025-05-14 to 2026-05-20) with constant 0.0001 values. Consider removing MATIC from the strategy universe or replacing with a new symbol.
