# Skill: ETL Management

Loaded by: ETL Manager agent

---

## 1. Daily refresh order

Always run in this sequence. Each layer depends on the previous.

```
bronze/   → Raw ingestion from all source systems
silver/   → Clean, validate, normalise
gold/     → Curate by asset type
              equity → strategy → fx → crypto → commodity → market → portfolio → ipo
consumption/ → Serve by frontend tab
              command → lab → performance → portfolio → market
```

Run: `python agents/etl/daily_refresh.sh`

If any bronze source fails, continue the rest. Log the failure.
Do not abort the entire refresh for one broken source.

---

## 2. Data sources and credentials

| Source     | Script                           | Credential env var              | Public? |
|------------|----------------------------------|---------------------------------|---------|
| yfinance   | bronze/yfinance/ingest_yfinance.py | none                           | Yes     |
| FMP        | bronze/fmp/ingest_fmp.py         | FMP_API_KEY                     | No      |
| Binance    | bronze/binance/ingest_binance.py | BINANCE_API_KEY, BINANCE_SECRET | No      |
| Coinbase   | bronze/coinbase/ingest_coinbase.py | COINBASE_API_KEY, COINBASE_API_SECRET | No |
| IBKR       | bronze/ibkr/ingest_ibkr.py       | IBKR_HOST, IBKR_PORT, IBKR_CLIENT_ID | No |
| HKEX       | bronze/hkex/ingest_hkex.py       | none (public scrape)           | Yes     |
| manual     | bronze/manual/ingest_manual.py   | operator-supplied file          | Manual  |

When a credential is missing or rejected:
1. Log which source failed and the exact error (401, connection refused, etc.)
2. Stop that source's ingestion only — do not halt the full refresh
3. Message the operator via Telegram: exactly which key is needed and what format
4. Wait for the operator to supply it before retrying that source

---

## 3. Receiving credentials from the operator

When the operator sends a new API key:
1. Confirm receipt: "Received FMP_API_KEY — setting environment variable."
2. Set via `os.environ` for the current session
3. Retry the failed ingestion script immediately
4. Confirm success or report the new error

Never log credential values. Never echo them back to the operator.

---

## 4. Manual data loads

The operator may send CSV files for `bronze/manual/`. Protocol:

1. Receive file path or content from operator
2. Parse and summarise: row count, tickers, date range, any nulls
3. Confirm with operator before writing: "47 rows, AAPL 2024-01-01 to 2024-06-30. Write to bronze.manual_prices? (yes/no)"
4. On confirmation: run `bronze/manual/ingest_manual.py`
5. Report rows written and any rejected rows

---

## 5. Status reporting

When the operator asks "status" or "last refresh":

```
ETL status as of {timestamp}:
  Last full refresh: {datetime} — {ok/partial/failed}
  Bronze sources:    FMP ✓  yfinance ✓  Binance ✗ (key expired)  Coinbase ✓  IBKR ✓  HKEX ✓
  Silver:            clean_prices ✓  clean_earnings ✓  ...
  Gold:              equity ✓  strategy ✓  fx ✓  crypto ✓  commodity ✓  market ✓
  Consumption:       command ✓  lab ✓  performance ✓  portfolio ✓  market ✓
  Next scheduled:    {datetime}
```

---

## 6. Emitting events

On successful full refresh:
```python
emit_event(
    event_type='etl.completed',
    payload={'refresh_date': today, 'sources_ok': [...], 'sources_failed': [...]},
    source_agent='qr_etl_manager',
    domain='quant'
)
```

On partial failure (some sources failed, rest succeeded):
```python
emit_event(
    event_type='etl.partial',
    payload={'refresh_date': today, 'sources_ok': [...], 'sources_failed': [...], 'reason': '...'},
    source_agent='qr_etl_manager',
    domain='quant'
)
```

On total failure (bronze layer could not run at all):
```python
emit_event(
    event_type='etl.failed',
    payload={'refresh_date': today, 'reason': '...'},
    source_agent='qr_etl_manager',
    domain='quant'
)
```

---

## 7. Failure handling

| Failure type         | Action                                                   |
|----------------------|----------------------------------------------------------|
| Missing credential   | Skip source, alert operator, wait for key               |
| API rate limit       | Retry after 60s × 3, then skip and alert                |
| DB write error       | Retry once, then emit etl.failed and alert operator     |
| Script crash         | Log traceback, continue remaining scripts               |
| Full refresh failure | Emit etl.failed, alert operator with specific reason    |

Always continue past individual script failures. A broken FMP ingest
must not prevent yfinance or HKEX from running.
