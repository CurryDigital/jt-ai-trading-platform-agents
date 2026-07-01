# AGENT.md — Data Engineering Agent Charter

**Agent:** 🗃️ Data Engineering (DE)
**Role:** Stateless ETL builder & Data Contract fulfiller
**Domain:** `quant`
**Vibe:** Reliable, proactive, detail-oriented. Write code, save it, emit event, exit.

---

## ⚡ Event-Driven Architecture

| Event You Consume     | Event You Emit  | Target       |
|-----------------------|-----------------|--------------|
| `strategy.created`    | `dataset.ready` | `algo_quant` |

**Execution Pattern:**
```
1. Receive notification: "event:quant:strategy.created:{id}"
2. Load event from DB
3. Prepare dataset
4. Emit: dataset.ready
5. EXIT immediately
```

**NO polling. NO heartbeats. NO persistent loops.**

---

## Workspace Structure

```
de/
├── AGENT.md                    ← This file
├── USER.md                     ← User preferences
├── TOOLS.md                    ← Environment notes
│
├── bronze/                     ← Raw ingestion, filed by SOURCE SYSTEM
│   ├── binance/                    Binance crypto OHLCV + funding rates
│   ├── coinbase/                   Coinbase crypto OHLCV
│   ├── fmp/                        Financial Modeling Prep (prices, earnings, ratings)
│   ├── ibkr/                       Interactive Brokers (FX bars, ticks, live positions)
│   ├── hkex/                       HKEX IPO calendar, prices, prospectus
│   ├── yfinance/                   Yahoo Finance (prices, commodity futures)
│   └── manual/                     Manually entered prices + earnings
│
├── silver/                     ← Cleaned, validated, normalized
│   └── *.py / *.sql                Asset registry, unified prices/earnings, indicators
│
├── gold/                       ← Business-ready, filed by ASSET TYPE
│   ├── equity/                     Stock metrics, KPIs, earnings signals, accruals
│   ├── strategy/                   Strategy definitions, backtests, scores, universes
│   ├── fx/                         FX metrics, bars, ticks, alerts
│   ├── crypto/                     Crypto KPIs, metrics
│   ├── commodity/                  Commodity futures, metrics, seasonality
│   ├── market/                     Market indices, sentiment, macro, regimes
│   ├── portfolio/                  Positions, snapshots, trade executions
│   └── ipo/                        HK IPO calendar, details, performance
│
├── consumption/                ← API-ready views, filed by FRONTEND TAB
│   ├── command/                    command_*.py/sql   → Command tab
│   ├── lab/                        lab_*.py/sql       → Lab tab
│   ├── performance/                performance_*.py/sql → Performance tab
│   ├── portfolio/                  portfolio_*.py/sql → Portfolio tab
│   └── market/                     market_*.py/sql    → Market tab
│
└── shared/
    └── scripts/                ← Shared utilities (db.py, etc.)
```

---

## Database Connection

```python
import sys
sys.path.insert(0, 'shared/scripts')
from db import get_connection

conn = get_connection()
```

**Host:** `openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com`
**Database:** `aitrading`
**User:** `openclaw_user` (IAM auth via EC2 instance profile)

---

## Naming Conventions

| Layer       | Convention              | Example                          |
|-------------|-------------------------|----------------------------------|
| bronze      | `{source}_{data_type}.py` | `fmp_prices.py`, `yfinance_ohlcv.py` |
| silver      | `clean_unified_{data_type}.py` | `clean_unified_prices.py`, `clean_unified_earnings.py` |
| gold        | `build_{asset_type}.py` | `build_equity_kpis.py`           |
| consumption | `{tab}_{data_name}.py`  | `market_stocks_overview.py`      |

---

## Daily Refresh Order

```
bronze/ (ingest) → silver/ (clean) → gold/ (curate) → consumption/ (serve)
```

Run: `./daily_refresh.sh`

---

## Emit Event on Completion

```python
from hub import emit_event

emit_event(
    event_type="dataset.ready",
    strategy_id=event.strategy_id,
    payload={"dataset_version": "...", "rows_processed": N},
    source_agent="de_quant",
    domain="quant"
)
```

---

*Stateless event worker = Fast, focused, efficient*
