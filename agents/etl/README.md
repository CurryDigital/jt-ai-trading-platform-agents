# qr_etl — Regime Detection Engine

## What this does

A 4-stage ETL pipeline that ingests market data, trains a 3-state Gaussian Hidden Markov Model on regime features, and produces a single daily regime label (`gold.regime_label`) that routes 20 trading strategies into one of five regimes: TREND, MEAN_REV, CARRY, EVENT, or FLAT.

## Prerequisites

- Python 3.10+
- PostgreSQL 14+ (production: AWS RDS)
- `hmmlearn`, `scikit-learn`, `joblib`, `pandas`, `numpy`, `psycopg2`, `requests`, `beautifulsoup4`

```bash
pip install -r requirements.txt
```

## Setup

1. Clone the repo
2. `cp .env.template .env`
3. Fill in:
   - `FRED_KEY` — for macro data (optional, fallback included)
   - `DATA_PATH` — local data directory
   - `DB_CONNECTION_STRING` — PostgreSQL connection string
4. `pip install -r requirements.txt`
5. `python run_daily.py`

## Running the pipeline

```bash
# Daily run (normal mode, < 5 min)
python run_daily.py

# Weekly aux data (earnings + holdings — run separately, ~10-15 min)
python bronze/yfinance/ingest_yfinance_aux.py

# Run tests
pytest tests/test_regime.py -v

# Full history rebuild
python run_daily.py --backfill
```

## Output

**Primary output table:** `gold.regime_label`

| Column | Type | Description |
|--------|------|-------------|
| date | DATE PK | Trading day |
| regime | VARCHAR(10) | Final label: TREND, MEAN_REV, CARRY, EVENT, FLAT |
| hmm_label | VARCHAR(10) | Raw HMM state (audit) |
| override_used | BOOLEAN | True if rule fired, False if HMM fallback |
| confidence | FLOAT | Max posterior probability from HMM |
| severity | INT | Event severity (0=none, 1=EIA, 2=CPI/NFP, 3=FOMC) |

**Query today's regime:**
```python
from regime.regime_rules import get_active_strategies
print(get_active_strategies())
```

## Regime labels and strategy routing

| Regime | Active Strategies | Condition |
|--------|-------------------|-----------|
| TREND | 1, 2, 6, 11, 15, 16, 18 | ADX > 22, H > 0.55, vol expanding |
| MEAN_REV | 3, 5, 8, 10, 13, 14, 19, 20 | ADX < 22, vol contracting, fear subsided |
| CARRY | 7, 17 | RV/IV < 0.80, VIX z-score < 0 |
| EVENT | 4, 12 | High-severity macro release (FOMC, CPI, NFP) |
| FLAT | — | VIX z-score > 2.5 (panic — all strategies off) |

**EIA Wednesdays:** Strategy 12 is additively included regardless of base regime.

## Architecture

```
Stage 1 — INGEST (bronze)
  ├── yfinance/ingest_yfinance.py
  ├── yfinance/ingest_vix.py
  ├── binance/ingest_binance.py
  ├── binance/ingest_funding_rates.py
  ├── cftc/ingest_cot_euro_fx.py
  └── macro/ingest_macro_calendar.py

Stage 2 — SILVER (clean)
  └── clean_prices.py

Stage 3 — GOLD (analytics)
  └── gold_builder.py
      ├── build_daily_ohlcv()
      ├── build_vix_regime()
      ├── build_macro_flags()
      ├── build_funding_metrics()
      ├── build_cot_sentiment()
      ├── compute_features()      ← 11 features
      ├── train_hmm()             ← 3-state GaussianHMM
      └── build_regime_label()    ← rule override + HMM fallback

Stage 4 — REPORT
  └── Today's regime + structured log
```

### Goals completed

- **Goal 1:** Data ingestion (yfinance, VIX, Binance, CFTC, FRED macro)
- **Goal 2:** Feature engineering (ADX, Hurst, RV, VIX z-score, breadth, etc.)
- **Goal 3:** HMM training (3 states, 6 features, 756-day rolling window)
- **Goal 4:** Rule-override layer (5 regimes, strategy router, EIA add-on)
- **Goal 5:** Orchestrator, tests, documentation

## Known limitations

- `funding_z` pre-2025 is set to 0.0 (neutral) — Binance funding data only available from 2025
- Hurst exponent on short windows (30 days) is noisy — used as a weak signal
- COT data has a 77-day gap in 2025 due to CFTC reporting delays
- Macro event calendar uses hardcoded fallback schedules for BLS/FOMC (web scraping blocked by 403)
- EIA Wednesdays are generated programmatically; actual holiday closures may differ

## File layout

```
etl/
├── run_daily.py              ← Main orchestrator
├── gold/gold_builder.py      ← Gold layer builder
├── regime/
│   ├── train_hmm.py          ← HMM trainer
│   ├── regime_rules.py       ← Rule engine + strategy router
│   └── hmm_model.pkl         ← Serialized model
├── bronze/macro/
│   └── ingest_macro_calendar.py  ← Actual release dates
├── tests/
│   └── test_regime.py        ← 9 pytest cases
├── logs/                     ← Daily run logs (run_YYYYMMDD.log)
└── README.md                 ← This file
```

## Error handling

- Bronze scripts retry 3× with 30s backoff
- Stage 1/2 failure → abort with exit code 1 (no gold on stale data)
- Stage 3 failure → log warning, continue (yesterday's labels still valid)
- Stage 4 failure → log warning only
- All logs written to `logs/run_YYYYMMDD.log`
