# SPEC — gold.daily_ohlcv write-time validation + deadman both directions

Date: 2026-10-16
Owner: qr_etl (spec + deadman implementation target)

## Goal

No invalid OHLCV row reaches gold.daily_ohlcv silently. Validation happens at
write time in every writer path, and the nightly deadman audits the same rules
in both calendar directions (missing AND extra rows).

## Write-time validation rules (per row)

Reject/quarantine before insert/update when any rule fails:

1. Identity: ticker present in gold.asset_registry; date not in the future.
2. OHLC sanity: close IS NOT NULL and close > 0; when open/high/low exist,
   high >= low, high >= open/close, low <= open/close.
3. Volume: volume IS NULL or volume >= 0; zero-volume equity rows are allowed
   only when explicitly quarantined as suspect placeholders.
4. Returns: returns_1d / returns_log must be finite (no NaN/Inf); abs returns
   above the asset-class band require a matching gold.price_adjustment_factors
   row (split/reverse_split/spinoff applied=true) or a suspect-bar reference.
5. Calendar: date must be a valid trading day for the row's market calendar,
   except asset classes with legitimate weekend/overnight sessions (FX Sunday
   bars, crypto). Extra rows on closed days are rejected unless covered by an
   explicit calendar exception.
6. Provenance: primary_source non-empty; full-history restates must carry a
   snapshot id (see 2026-10-16_etl_snapshot_log.sql policy).

## Enforcement points

- Shared validator: `agents/etl/shared/scripts/ohlcv_validate.py` (new).
- Writers that must call it before write: `gold/gold_builder.py`,
  `silver/clean_unified_prices.py` boundary into gold consumers,
  `workspace/oneoff/heal_gold_from_silver_v1.py`, split/spin-off fix scripts,
  and any manual backfill script.
- DB backstop (migration later): CHECK constraints for finite positives and
  high/low ordering; calendar legality stays in application code because it is
  market-specific and exception-driven.

## Deadman consumption (nightly)

`derivatives/pipeline_deadman.py` gains a gold.daily_ohlcv section:

- Missing days: for each active ticker group (US equity, HK equity, SI equity,
  FX, index), compare gold dates vs the exchange calendar for the trailing
  window; alert only after the date's load tick has passed.
- Extra days: alert on gold rows whose date is not a valid trading day for the
  row's calendar, excluding registered exceptions (FX Sunday, crypto).
- NaN/Inf: scan gold.daily_ohlcv returns/OHLC and feature tables for NaN/Inf.
- Signal freshness: for strategies due to rebalance, verify latest
  gold.strategy_ticker_scores.computed_at is on/after the expected signal date;
  stale scores alert even when prices are fresh.

Alert format stays one line per violation class with counts and examples.
