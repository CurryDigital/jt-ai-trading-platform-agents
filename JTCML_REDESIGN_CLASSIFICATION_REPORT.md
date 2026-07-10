# JTCML Redesign DB Object Classification Report

## 1. Scope
All new tables and views created in migration 002 (`002_frontend_v2_alignment.sql`) and related builders under:
- `/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/etl`
- `/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/signals`

Pipeline definitions per owner directive:
- **Daily refresh (data-related)**: ingestion, cleaning, and materialization of market/portfolio data.
- **Signal generation (signal-related)**: strategy signal scoring, evaluation, performance, and proximity.

---

## 2. Redesign DB Object Classification

| # | DB Object / View | Schema | Pipeline | Owner / Builder Exists | Notes |
|---|-------------------|--------|----------|------------------------|-------|
| 1 | `account_nav_daily` | `gold` | **Daily refresh** | No dedicated builder | Seed table for equity curve; currently empty. Needs builder from IBKR NAV snapshots. |
| 2 | `signal_families` | `gold` | **Signal generation** | Seed in migration only | Static vocabulary; runtime changes rare. |
| 3 | `manual_orders` | `gold` | **Daily refresh** (fold-in) | **Missing** | Platform write target; needs daily fold-in to `consumption.portfolio_positions_current`. |
| 4 | `regime_forecast` | `gold` | **Daily refresh** | `gold/market/build_regime_forecast.py` | Persistence baseline only; empty for non-US scopes. |
| 5 | `macro_kpis_facts` | `gold` | **Daily refresh** | `gold/market/build_macro_kpis.py` | Stub values; depends on sentiment/breadth. |
| 6 | `macro_sectors_facts` | `gold` | **Daily refresh** | `gold/market/build_macro_sectors.py` | US ETFs + HK sector approximation. |
| 7 | `economic_calendar` | `gold` | **Daily refresh** | `gold/market/build_economic_calendar.py` | US events only; HK source not wired. |
| 8 | `news_sentiment` | `gold` | **Daily refresh** | `gold/market/build_market_news.py` | Sample headlines; replace with real API later. |
| 9 | `market_sentiment_facts` | `gold` | **Daily refresh** | `gold/market/build_market_sentiment.py` | One row per region (`US`, `HK`); derived from `gold.vix_regime` and `gold.index_metrics` (^HSI). |
| 10 | `market_breadth_facts` | `gold` | **Daily refresh** | `gold/market/build_market_breadth.py` | From `daily_ohlcv` + `asset_registry`. |
| 11 | `market_movers_facts` | `gold` | **Daily refresh** | `gold/market/build_market_movers.py` | Top 10 gainers/losers per region. |
| 12 | `signal_evaluations` | `gold` | **Signal generation** | `signals/strategies/build_signal_redesign.py` | Bridges `strategy_ticker_scores` to family vocabulary. |
| 13 | `signal_family_performance` | `gold` | **Signal generation** | `signals/strategies/build_signal_redesign.py` | Derived from `signal_evaluations`. |
| 14 | `signal_proximity_facts` | `gold` | **Signal generation** | `signals/strategies/build_signal_redesign.py` | Derived from `signal_evaluations`. |
| 15 | `attention_items` | `gold` | **Daily refresh** | `gold/strategy/build_attention_items.py` | Action Center; derived from existing sources. |
| 16 | `ib_gateway_heartbeat` | `gold` | **Daily refresh** | `gold/market/build_ib_gateway_state.py` | Also needs lightweight cron for live status. |
| 17 | `risk_limits_facts` | `gold` | **Signal generation** / risk | **Missing** | Per-strategy + global risk limits. No builder. |
| 18 | `consumption.account_summary` | `consumption` | view | n/a | Derived from `gold.account_nav_daily`; no live positions yet. |
| 19 | `consumption.account_equity_curve` | `consumption` | view | n/a | Derived from `gold.account_nav_daily`. |
| 20 | `consumption.attention_queue` | `consumption` | view | n/a | Derived from `gold.attention_items`. |
| 21 | `consumption.dashboard_indices` | `consumption` | view | n/a | Filters `consumption.dashboard_market_overview`. |
| 22 | `consumption.market_breadth` | `consumption` | view | n/a | Wraps `gold.market_breadth_facts`. |
| 23 | `consumption.market_sentiment` | `consumption` | view | n/a | Wraps `gold.market_sentiment_facts`; exposes `region`, `regime`, `fear_greed`. |
| 24 | `consumption.market_movers` | `consumption` | view | n/a | Wraps `gold.market_movers_facts`. |
| 25 | `consumption.macro_regime_7d` | `consumption` | view | n/a | Wraps `gold.regime_forecast`. |
| 26 | `consumption.macro_kpis` | `consumption` | view | n/a | Wraps `gold.macro_kpis_facts`. |
| 27 | `consumption.macro_sectors` | `consumption` | view | n/a | Wraps `gold.macro_sectors_facts`. |
| 28 | `consumption.macro_events` | `consumption` | view | n/a | Wraps `gold.economic_calendar`. |
| 29 | `consumption.market_news` | `consumption` | view | n/a | Wraps `gold.news_sentiment`. |
| 30 | `consumption.signal_setups` | `consumption` | view | n/a | Pivots `gold.signal_evaluations`. |
| 31 | `consumption.signal_performance` | `consumption` | view | n/a | Wraps `gold.signal_family_performance`. |
| 32 | `consumption.signal_proximity` | `consumption` | view | n/a | Wraps `gold.signal_proximity_facts`. |
| 33 | `consumption.signal_feed` | `consumption` | view | n/a | Wraps `consumption.signal_logs`. |
| 34 | `consumption.execution_order_queue` | `consumption` | view | n/a | From `gold.ibkr_orders`. |
| 35 | `consumption.execution_fills` | `consumption` | view | n/a | From `gold.trade_executions`. |
| 36 | `consumption.ib_gateway_state` | `consumption` | view | n/a | Wraps `gold.ib_gateway_heartbeat`. |
| 37 | `consumption.risk_limits` | `consumption` | view | n/a | Wraps `gold.risk_limits_facts`. |
| 38 | `consumption.portfolio_positions_current.source` | `consumption` | column | n/a | Distinguishes algo vs manual positions; needs fold-in logic. |

---

## 3. Missing Builders / Gaps

| # | Object / Capability | Pipeline | Why Missing | Recommended Action |
|---|---------------------|----------|-------------|------------------|
| 1 | `gold.risk_limits_facts` builder | Signal cycle | No file writes to it; no risk-limit ingestion source. | Create `gold/strategy/build_risk_limits.py` or `agents/signals/strategies/build_risk_limits.py` reading strategy registry + global halt flags. |
| 2 | `gold.account_nav_daily` builder | Daily refresh | No NAV snapshot builder; equity curve empty. | Create `gold/portfolio/build_account_nav_daily.py` from `gold.ibkr_account_summary` or `gold.portfolio_snapshots`. |
| 3 | `gold.manual_orders` → `consumption.portfolio_positions_current` fold-in | Daily refresh | `manual_orders` is platform-write; no ETL job consumes it. | Add step in `gold/portfolio/build_portfolio_snapshot.py` or new `gold/portfolio/build_manual_positions.py` to union manual rows with `source='manual'`. |
| 4 | `gold.ib_gateway_heartbeat` frequent refresh | Daily refresh (also live) | Only daily now; UI needs live status. | Optional: add a lightweight 1-minute cron calling `build_ib_gateway_state.py` (idempotent). |
| 5 | `consumption.account_summary` real data | Daily refresh | View is currently empty (NAV missing). | Unblocked once `account_nav_daily` builder lands. |

---

## 4. Recommended Script Edits (No Files Modified)

### 4.1 `daily_refresh.sh` — `/home/ubuntu/.hermes/profiles/qr_etl/scripts/daily_refresh.sh`

Existing `gold/market/*.py` sweep already catches most daily redesign builders:
- `build_macro_kpis.py` → `macro_kpis_facts`
- `build_market_news.py` → `news_sentiment`
- `build_ib_gateway_state.py` → `ib_gateway_heartbeat`
- `build_macro_sectors.py` → `macro_sectors_facts`
- `build_economic_calendar.py` → `economic_calendar`
- `build_market_breadth.py` → `market_breadth_facts`
- `build_market_movers.py` → `market_movers_facts`
- `build_market_sentiment.py` → `market_sentiment_facts`
- `build_regime_forecast.py` → `regime_forecast`
- `build_attention_items.py` → `attention_items` (via `gold/strategy` sweep)

**Missing: explicit guarantees for redesign objects not in the directory sweeps, and the new builders once written.**

Recommended additions (insert after the explicit `run_gold` calls and before the consumption sweep, around line 323):

```bash
# ════════════════════════════════════════════
# JTCML Redesign explicit gold builders (not caught by directory sweeps)
# ════════════════════════════════════════════
run_gold "Account NAV daily"          "${ETL_ROOT}/gold/portfolio/build_account_nav_daily.py" || true
run_gold "Manual positions fold-in"   "${ETL_ROOT}/gold/portfolio/build_manual_positions.py" || true
run_gold "Redesign signal vocab bridge" "${ETL_ROOT}/../signals/strategies/build_signal_redesign.py" || true
```

Note: `build_signal_redesign.py` technically belongs in the signal cycle, but it only reads `gold.strategy_ticker_scores` (already built by daily `gold/strategy/build_strategy_scores.py`). To keep it out of daily refresh, wire it in `run_signal_cycle.sh` instead (Section 4.2).

Also update the preflight `REQUIRED_SCRIPTS` list (around line 54) to include the new builders so the script aborts if they are missing before any real run:

```bash
REQUIRED_SCRIPTS=(
    "${ETL_ROOT}/shared/scripts/ingest_binance_crypto.py"
    "${ETL_ROOT}/silver/crypto_normalize.py"
    "${ETL_ROOT}/silver/compute_technical_indicators.py"
    "${ETL_ROOT}/silver/clean_unified_prices.py"
    "${ETL_ROOT}/gold/gold_builder.py"
    "${ETL_ROOT}/gold/crypto/build_crypto_kpis.py"
    "${ETL_ROOT}/gold/equity/build_stock_metrics.py"
    "${ETL_ROOT}/gold/equity/build_stock_metrics_history.py"
    "${ETL_ROOT}/gold/portfolio/build_account_nav_daily.py"
    "${ETL_ROOT}/gold/portfolio/build_manual_positions.py"
    "${ETL_ROOT}/sync_gold_layer_state.py"
)
```

### 4.2 `run_signal_cycle.sh` — `/home/ubuntu/.hermes/profiles/qr_etl/home/trading-platform/agents/signals/run_signal_cycle.sh`

Current script only runs `strategies/run_signals.py`. It does **not** bridge redesign signal tables (`signal_evaluations`, `signal_family_performance`, `signal_proximity_facts`) or build risk limits.

Recommended additions (insert after the `run_signals.py` call, around line 86):

```bash
# ════════════════════════════════════════════
# JTCML Redesign signal-consumption bridge + risk limits
# ════════════════════════════════════════════
cd "${SIGNALS_DIR}"

# Bridge legacy strategy scores into redesign signal tables
"${PYTHON}" strategies/build_signal_redesign.py
RC2=$?
if [ $RC2 -ne 0 ]; then
    echo "⚠️ build_signal_redesign.py failed (exit $RC2)"
    # Decide whether to fail hard or continue; signal tables are display-only.
fi

# Risk limits: per-strategy + global halt flags
"${PYTHON}" strategies/build_risk_limits.py
RC3=$?
if [ $RC3 -ne 0 ]; then
    echo "⚠️ build_risk_limits.py failed (exit $RC3)"
fi

# Aggregate exit code for monitoring (run_signals.py is primary)
if [ $RC -ne 0 ] || [ $RC2 -ne 0 ] || [ $RC3 -ne 0 ]; then
    echo "SIGNAL CYCLE completed with failures — primary=$RC redesign=$RC2 risk=$RC3"
    exit 1
fi
```

Also consider adding a direct freshness check for `gold.strategy_ticker_scores` before the redesign bridge:

```bash
# Ensure the gold layer has fresh scores before bridging
SCORES_FRESH=$(${PYTHON} -c "import sys; sys.path.insert(0,'${ETL_SHARED}'); from db import get_connection; conn=get_connection(); cur=conn.cursor(); cur.execute(\"SELECT MAX(updated_at) FROM gold.strategy_ticker_scores\"); row=cur.fetchone(); conn.close(); print(row[0].isoformat() if row and row[0] else 'empty')")
echo "Latest strategy_ticker_scores updated_at: ${SCORES_FRESH}"
```

---

## 5. Summary of Findings

- **Existing daily redesign builders** are already picked up by the `gold/market/*.py` directory sweep in `daily_refresh.sh`. No action needed for them, but **explicit calls are safer** because directory sweeps can silently skip if a file is moved or renamed.
- **Missing builders**: `build_account_nav_daily.py`, `build_manual_positions.py` (or equivalent fold-in), and `build_risk_limits.py`. These should be created before wiring.
- `build_signal_redesign.py` exists and is the correct place for `signal_evaluations`, `signal_family_performance`, and `signal_proximity_facts`; it belongs in the **signal generation pipeline**, not daily refresh.
- `manual_orders` is a platform-write table and must be folded into `consumption.portfolio_positions_current` with `source='manual'` via a daily refresh builder.
- `risk_limits_facts` has no writer and no upstream source; it needs a new builder (likely in `agents/signals/` because it is strategy + global halt metadata).

---

*Report generated without modifying any files.*
