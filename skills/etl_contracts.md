# Skill: ETL Contracts

## Purpose
Defines what the ETL layer must deliver into the gold tables for the
research pipeline to function. DE agent depends on these contracts
being met. If ETL is stale or broken, DE will fail quality gates and
the entire pipeline stalls.

Load this skill: DE agent (consumer), ETL processes (producer).

---

## Primary data contract: gold.stock_metrics_history

This is the table DE agent reads for all equity/ETF backtests.

```sql
-- Minimum required columns
ticker          TEXT NOT NULL
date            DATE NOT NULL
open            NUMERIC
high            NUMERIC
low             NUMERIC
close           NUMERIC NOT NULL   -- required for all checks
volume          BIGINT
adj_close       NUMERIC            -- preferred over close for split-adjusted backtests

PRIMARY KEY (ticker, date)
```

### Freshness requirement
- Must be updated daily by 06:00 SGT (before the nightly experiment cycle)
- DE agent Gate 1 will fail if data is more than 2 trading days stale
- ETL writer: write to `gold.stock_metrics_history` (NOT the view `gold.stock_metrics`)

### Coverage requirement
For any ticker in asset_universe:
- Must have data from at least 5 years before the earliest experiment date_range.start
- This ensures Gate 5 (2× lookback depth) can always be satisfied

---

## Secondary contracts (used by DE quality stubs when connected)

### Feature pipeline (Gate 2 — lookahead bias check)
When connected, must provide:
```sql
gold.features (ticker, date, feature_name, feature_value, computed_as_of_date)
```
`computed_as_of_date` must be ≤ `date` for all rows — no lookahead.

### Market data (Gate 4 — spike check)
When connected, must provide real-time OHLCV with the same schema as
gold.stock_metrics_history. Spike detection uses a rolling 20-day window.

---

## ETL run order (from daily_refresh.sh)

```
1. bronze/ (raw ingest from all sources)
   └── fmp, yfinance, ibkr, binance, coinbase, hkex, manual

2. silver/ (clean and normalise)
   └── clean_prices, clean_earnings, clean_technical_indicators,
       clean_unified_prices, clean_unified_earnings,
       compute_technical_indicators, sync_asset_registry

3. gold/ (build business-ready tables)
   └── equity: build_stock_metrics_history ← most critical for pipeline
   └── equity: build_equity_kpis, build_earnings_signals
   └── other asset classes: crypto, fx, commodity, ipo, market, portfolio

4. consumption/ (API views for frontend)
   └── command, lab, performance, portfolio, market
```

`build_stock_metrics_history.py` must run and commit successfully
before any experiment started that day can proceed past DE.

---

## Critical constraint: gold.stock_metrics is READ-ONLY

`gold.stock_metrics` is a VIEW over `gold.stock_metrics_history`.
ETL writers must write to `gold.stock_metrics_history`.
The Platform FastAPI reads from `gold.stock_metrics` (the view) — no change needed there.
The DE agent reads from `gold.stock_metrics_history` directly — no change needed there.

If an ETL job still writes to `gold.stock_metrics` directly, it will fail silently
and new data will not appear in the view. This is the most common ETL misconfiguration.

---

## Monitoring ETL health (for Monitor agent awareness)

If DE fails Gate 1 repeatedly (missing bars), check:
1. Was `daily_refresh.sh` run today? Check logs at `/home/ubuntu/.openclaw/workspace/de/logs/`
2. Did `build_stock_metrics_history.py` complete without error?
3. Is `gold.stock_metrics_history` current? Run:
   ```sql
   SELECT MAX(date) FROM gold.stock_metrics_history WHERE ticker = 'AAPL'
   ```
   Expected: yesterday's date on a trading day.

If stale, re-run the ETL manually:
```bash
cd /home/ubuntu/.openclaw/workspace/de
python gold/equity/build_stock_metrics_history.py
```
