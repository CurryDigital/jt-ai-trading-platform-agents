# A+H Twin Mapping — kanban t_5d325908 (2026-09-22)

Consumer: hypothesis `hk_ipo_ah_discount_convergence_v1` (spec: qr_research workspace hk_ipo_ah_batch/SPEC.md).

## Event set
201 Main-board IPOs since 2024-01-01 with `stock_name ILIKE '%- H Shares%'`
(silver.unified_ipo_calendar). The '- H Shares' suffix marks PRC-incorporated
issuers; it does NOT imply an A-share twin exists. Verified outcome:

- 55  mapped    -> `a_twin_status='mapped'`,   `a_twin_ticker` set
- 146 no_a_twin -> `a_twin_status='no_a_twin'` (H-share-only issuer, no A listing)
- 0   unprocessed

## Schema (migration applied 2026-09-22)
silver.unified_ipo_calendar:
- `a_twin_ticker varchar(16)`  — DB convention `.SS`/`.SZ` (yfinance-compatible,
  matches pre-existing CN universe; .SS = Shanghai, NOT .SH)
- `a_twin_status varchar(16)`  — 'mapped' | 'no_a_twin'
- `a_twin_source varchar(40)`  — 'etnet_ah' | 'eastmoney_suggest+f10_verify' |
  'etnet_ah+eastmoney_suggest_no_result'
- index `idx_unified_ipo_calendar_a_twin` on a_twin_ticker (partial)

## Method
1. etnet A+H list (etnet.com.hk) scrape -> primary mapping (H code -> A code).
2. eastmoney suggest API + F10 issuer verification for residual names
   (name matching alone is fragile: '- H Shares' suffix names differ from
   A-share names; issuer identity verified via F10 company profile).
3. Events with no verified A-share issuer match -> 'no_a_twin'. Spot audit of
   exclusions confirmed genuine H-only issuers (MIXUE, Laopu Gold, Chery,
   Mao Geping, Dobot, InnoScience, Unisound, Geek+, Biren, CF PharmTech, ...).
   Note: 3636.HK (Yunnan Jinxun) has a Beijing Stock Exchange listing (870844.BJ)
   only — out of .SS/.SZ scope and not covered by yfinance; excluded.

## Prices loaded (2026-09-22)
- 55 A twins: silver.unified_prices market='CN' (and bronze.yf_prices),
  history from 2023-01-01 (>= 60 trading days before earliest 2024 listing)
  through 2026-09-22. Min 602 rows/twin, min 439 pre-listing trading days,
  0 NULL closes, returns_1d/returns_log/adjusted_close backfilled.
- FX: USDCNY=X and HKDCNY=X, market='FX', 1750 rows each 2020-01-01 ->
  2026-09-22 (bronze + silver). Registered in gold.asset_registry
  (asset_class='FX', market='FX', is_active).

## Refresh note
Daily refresh of CN/FX rows rides the normal yfinance silver merge pipeline
(tickers are now in gold.asset_registry is_active=TRUE, market CN/FX).
New A+H IPOs need `a_twin_*` populated at calendar-ingest time — currently a
manual step; automate in unified_ipo_calendar ingest if this strategy survives
pre-screen.

Source artifacts (mapping JSON, builder scripts): kanban task t_5d325908
workspace; mapping snapshot: ah_mapping_raw.json (55 mapped / 146 excluded
with reason='no_verified_twin').
