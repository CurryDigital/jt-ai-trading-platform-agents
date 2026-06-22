# COT Coverage Expansion — GC / CL / ES

## Status
YELLOW — ready for review. No DB writes executed yet.

## Objective
Expand `gold.cot_sentiment` from EURO FX only to include GC (Gold), CL (Crude Oil), and ES (S&P 500) futures non-commercial positioning, using the exact same schema and z-score methodology as the existing EURO FX data.

## Files

| File | Purpose |
|------|---------|
| `cot_ingest.py` | Ingest + transform + load for GC/CL/ES |
| `test_cot_expand.py` | Row count, z-score sanity, PK, structural pair tests |
| `README.md` | This file |

## Data Sources

| Ticker | CFTC Report | Contract Name | URL Pattern |
|--------|-------------|---------------|-------------|
| GC | Disaggregated Futures | `GOLD - COMMODITY EXCHANGE INC.` | `fut_disagg_txt_YYYY.zip` |
| CL | Disaggregated Futures | `WTI-PHYSICAL - NEW YORK MERCANTILE EXCHANGE` | `fut_disagg_txt_YYYY.zip` |
| ES | TFF (Traders in Financial Futures) | `S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE` | `fut_fin_txt_YYYY.zip` |

## Non-Commercial Construction

Matches EURO FX methodology exactly:

- **Disaggregated (GC, CL)**: `noncomm = Managed Money Long/Short + Other Reportables Long/Short`
- **TFF (ES)**: `noncomm = Asset Manager Long/Short + Leveraged Funds Long/Short + Other Reportables Long/Short`

## Z-Score Parameters

- Rolling window: **52 weeks × 7 days = 364 days**
- Computed on `net_noncomm` (long − short)
- Same formula as EURO FX ingest

## Daily Expansion Approach

**Weekly-only COT data → daily forward-fill with 3-day hard limit.**

This matches the existing EURO FX pattern in `gold.cot_sentiment`:
- Each calendar day gets the most recent weekly COT value
- Forward-fill stops after 3 days; gaps > 3 days raise `ValueError`
- Gaps between report dates > 7 days trigger a warning but do not block ingestion

**Data quality note**: COT has duplicate `report_date` rows because weekly data is forward-filled to daily. This is the same pattern as EURO FX. G4's frequency detector should filter zero gaps to get true weekly frequency.

## Historical Backfill

Downloads yearly zip files from **2021 through current year** (configurable in `YEARS` list). Deduplicates by `(instrument, report_date)` before daily expansion.

## Schema (`gold.cot_sentiment`)

| Column | Type | Notes |
|--------|------|-------|
| `instrument` | `character varying` | PK part 1; values: `EURO FX`, `GC`, `CL`, `ES` |
| `date` | `date` | PK part 2; calendar date (daily) |
| `report_date` | `date` | The Tuesday COT report date this row derives from |
| `noncomm_long` | `bigint` | Sum of non-commercial long positions |
| `noncomm_short` | `bigint` | Sum of non-commercial short positions |
| `net_noncomm` | `bigint` | `long − short` |
| `cot_z` | `numeric` | 364-day rolling z-score of `net_noncomm` |
| `sentiment` | `character varying` | `bullish` / `bearish` / `neutral` |
| `signal_flag` | `integer` | `1` if sentiment ≠ neutral, else `0` |
| `updated_at` | `timestamptz` | Last upsert time |

Primary key: `(instrument, date)`

## Sentiment Thresholds

| cot_z | Sentiment |
|-------|-----------|
| `> 1.0` | `bearish` (net long = crowded longs = bearish signal) |
| `< -1.0` | `bullish` (net short = crowded shorts = bullish signal) |
| otherwise | `neutral` |

## Success Criteria Checklist

- [ ] GC, CL, ES rows in `gold.cot_sentiment`
- [ ] `cot_z` and `sentiment` populated using same methodology as EURO FX
- [ ] No duplicate primary key violations
- [ ] G2's generator picks up new tickers automatically (reads `DISTINCT instrument` from table)
- [ ] G4's structural pair block (`cot_z ↔ net_noncomm`) applies without config change

## Running

```bash
cd ~/.hermes/profiles/qr_etl/home/trading-platform/agents/etl/workspace/cot_expansion
python cot_ingest.py      # ingest + transform + load
python test_cot_expand.py # validation suite
```

## Warnings

- **Do not run `cot_ingest.py` without review** — it will write to `gold.cot_sentiment`.
- The script uses `ON CONFLICT (instrument, date) DO UPDATE` so re-runs are safe (idempotent).
- If a ticker has < 52 weeks of history, it stores raw weekly rows without z-score (same fallback as EURO FX ingest).
