# ETL Pipeline for Quant Research

## Recent Changes (2026-03-21)

### Crypto Data Source Migration: Yahoo Finance → Binance

**What changed:**
- **Before:** Crypto data came from Yahoo Finance via `yfinance` (equities API repurposed for crypto)
- **After:** Crypto data now comes directly from **Binance API** (native crypto exchange)

**New files created:**

| Layer | Script | Purpose |
|-------|--------|---------|
| Bronze | `bronze/binance/crypto_ingest.py` | Pulls OHLCV data from Binance for 15 major pairs |
| Silver | `silver/crypto_normalize.py` | Normalizes raw Binance data, adds returns/volatility/VWAP |
| Gold | `gold/crypto/crypto_metrics.py` | Curates crypto metrics (RSI, MACD, Bollinger, Sharpe) |

**Data flow:**
```
Binance API
    ↓
bronze/binance/ (raw candlesticks)
    ↓
silver/crypto/ (normalized + derived metrics)
    ↓
gold/crypto/ (curated metrics matching stock schema)
    ↓
stock_metrics_history (unified table)
```

**Supported pairs:**
BTCUSDT, ETHUSDT, BNBUSDT, SOLUSDT, XRPUSDT, ADAUSDT, AVAXUSDT, DOTUSDT, MATICUSDT, LINKUSDT, UNIUSDT, LTCUSDT, ATOMUSDT, ETCUSDT, XLMUSDT

**Intervals:** 1d (daily), 4h, 1h

**Requirements:**
```bash
# Add to ~/.openclaw/.env
BINANCE_API_KEY=your_actual_api_key
BINANCE_SECRET=your_actual_secret
```

### Coinbase: Disabled (Binance Primary)

**Status:** ❌ Disabled — Using Binance as primary crypto source

**Why Binance over Coinbase:**
| Factor | Binance | Coinbase |
|--------|---------|----------|
| Rate limits | 1,200/min | 10/sec |
| Trading pairs | 1,500+ | ~250 |
| Auth complexity | HMAC (simple) | JWT (complex) |
| API maturity | Mature | Newer (Advanced Trade) |

**When to reactivate Coinbase:**
- US regulatory compliance required
- Binance data quality issues
- Need native USD pairs (not USDT)

**File:** `bronze/coinbase/crypto_ingest.py` (placeholder, ready if needed)

### FMP (Financial Modeling Prep) Activation

**What changed:**
- **New:** FMP API now active for equity fundamentals and historical prices
- **Limits:** 250 API calls/day, 512 MB/month bandwidth
- **Strategy:** Smart incremental backfill to stay within limits

**Features:**
- **Rate limiting:** Tracks API usage per day, stops before hitting limits
- **Incremental backfill:** Only fetches new data since last successful fetch
- **Priority queue:** 
  1. Real-time quotes (all 36 core tickers, batched)
  2. Historical prices (top 10 tickers, incremental)
  3. Fundamentals (top 5 tickers, if budget permits)

**Core tickers:**
AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, BRK-B, JPM, V, JNJ, WMT, UNH, MA, PG, HD, CVX, MRK, ABBV, PEP, KO, PFE, AVGO, COST, TMO, DIS, CSCO, VZ, ADBE, WFC, ACN, ABT, CRM, CMCSA, TXN, NKE

**File:** `bronze/fmp/ingest.py`

## Pipeline Structure

```
agents/etl/
├── bronze/           # Raw ingestion from source APIs
│   ├── binance/      # Binance crypto data ← PRIMARY
│   ├── coinbase/     # Coinbase (disabled — code remains for future use)
│   ├── fmp/          # Financial Modeling Prep (equities)
│   ├── ibkr/         # Interactive Brokers (portfolio)
│   ├── hkex/         # Hong Kong Exchange
│   ├── yfinance/     # Yahoo Finance (equities ONLY)
│   └── manual/       # Manual CSV uploads
├── silver/           # Clean & normalize
│   └── crypto_normalize.py  ← Binance source
├── gold/             # Curated by asset type
│   ├── crypto/       # Crypto metrics ← Binance source
│   ├── equity/       # Stock metrics
│   └── ...
├── consumption/      # Frontend-optimized tables
└── daily_refresh.sh  # Main orchestration script
```

## Running the Pipeline

```bash
# Full refresh
cd /home/ubuntu/.openclaw/workspace/quant_research/agents/etl
bash daily_refresh.sh

# Run just crypto bronze
python3 bronze/binance/crypto_ingest.py

# Run just crypto silver
python3 silver/crypto_normalize.py

# Run just crypto gold
python3 gold/crypto/crypto_metrics.py
```

## Next Steps

1. **✓ Binance credentials** — Already set in `~/.openclaw/.env`
2. **✓ FMP API key** — Already set in `~/.openclaw/.env`
3. **Test the pipeline** with full refresh:
   ```bash
   cd /home/ubuntu/.openclaw/workspace/quant_research/agents/etl
   bash daily_refresh.sh
   ```
4. **Monitor API usage** — Check `etl/.state/fmp_api_state.json` for FMP rate limit status
5. **Verify outputs**:
   - Binance: `bronze/binance/YYYYMMDD/*.parquet`
   - FMP: `bronze/fmp/YYYYMMDD/*.parquet`
   - Gold crypto: `gold/crypto/crypto_metrics_YYYYMMDD.parquet`
