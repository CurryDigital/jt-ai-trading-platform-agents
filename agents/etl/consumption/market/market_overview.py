#!/usr/bin/env python3
"""
Consumption: Market Tab — Stocks Overview, Commodities Overview, Dashboard Cards
Reads from: gold.kpis_metrics, gold.asset_registry, gold.strategy_ticker_scores,
            gold.commodity_futures, gold.commodity_metrics, gold.commodity_seasonality,
            gold.index_metrics, gold.market_sentiment_daily
Writes to:  consumption.markets_stocks_overview
            consumption.markets_commodities_overview
            consumption.dashboard_market_overview
            consumption.dashboard_summary_cards
            consumption.dashboard_opportunities_top
"""
import sys, os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SHARED = os.path.normpath(os.path.join(SCRIPT_DIR, '..', '..', 'shared', 'scripts'))
sys.path.insert(0, SHARED)
os.environ.setdefault('AWS_REGION', 'ap-southeast-1')
from db import get_connection

# ── Stocks Overview ───────────────────────────────────────────────────────────

STOCKS_SQL = """
INSERT INTO consumption.markets_stocks_overview
    (ticker, name, sector, industry, market,
     price, change_pct, change_value, volume, avg_volume, volume_ratio,
     trend, rsi_14, distance_to_52w_high_pct, distance_to_52w_low_pct,
     market_cap, pe_ratio, forward_pe, pb_ratio, dividend_yield,
     strategy_signals, top_strategy_score, signal, signal_strength,
     asset_class, updated_at)
WITH latest_kpis AS (
    SELECT DISTINCT ON (ticker) *
    FROM gold.kpis_metrics
    WHERE date >= CURRENT_DATE - INTERVAL '60 days'
    ORDER BY ticker, date DESC
),
strategy_agg AS (
    SELECT
        ticker,
        MAX(score)  AS top_strategy_score,
        -- Best signal action across all strategies
        (ARRAY_AGG(signal_action ORDER BY score DESC))[1] AS best_signal,
        MAX(LEAST(score / 100.0, 1.0)) AS signal_strength,
        jsonb_object_agg(strategy_id, score) AS strategy_signals
    FROM gold.strategy_ticker_scores
    WHERE signal_action IN ('BUY', 'SELL')
    GROUP BY ticker
)
SELECT
    ar.ticker,
    ar.name,
    ar.sector,
    NULL::varchar  AS industry,
    ar.market,
    k.close        AS price,
    k.change_1d    AS change_pct,
    ROUND((k.close * k.change_1d / 100.0)::numeric, 4) AS change_value,
    k.volume,
    k.vol_sma_20::bigint AS avg_volume,
    k.vol_ratio    AS volume_ratio,
    CASE
        WHEN k.close > k.sma_200 AND k.sma_50 > k.sma_200 THEN 'UP'
        WHEN k.close < k.sma_200 AND k.sma_50 < k.sma_200 THEN 'DOWN'
        ELSE 'SIDEWAYS'
    END AS trend,
    k.rsi_14,
    -- 52-week high/low distance: approximated from 200d SMA window
    NULL::numeric  AS distance_to_52w_high_pct,
    NULL::numeric  AS distance_to_52w_low_pct,
    NULL::bigint   AS market_cap,
    k.pe_ratio,
    NULL::numeric  AS forward_pe,
    NULL::numeric  AS pb_ratio,
    NULL::numeric  AS dividend_yield,
    COALESCE(sa.strategy_signals, '{}'::jsonb),
    sa.top_strategy_score,
    sa.best_signal AS signal,
    sa.signal_strength,
    ar.asset_class,
    NOW()
FROM gold.asset_registry ar
LEFT JOIN latest_kpis k  ON k.ticker = ar.ticker
LEFT JOIN strategy_agg sa ON sa.ticker = ar.ticker
WHERE ar.is_active = TRUE
  AND ar.asset_class IN ('equity', 'ETF')
ON CONFLICT (ticker) DO UPDATE SET
    price               = EXCLUDED.price,
    change_pct          = EXCLUDED.change_pct,
    volume              = EXCLUDED.volume,
    rsi_14              = EXCLUDED.rsi_14,
    trend               = EXCLUDED.trend,
    strategy_signals    = EXCLUDED.strategy_signals,
    top_strategy_score  = EXCLUDED.top_strategy_score,
    signal              = EXCLUDED.signal,
    signal_strength     = EXCLUDED.signal_strength,
    updated_at          = NOW();
"""

# ── Commodities Overview ──────────────────────────────────────────────────────

COMMODITIES_SQL = """
INSERT INTO consumption.markets_commodities_overview
    (ticker, name, category, exchange, price, change_pct, trend, rsi_14,
     current_month_bias, next_month_bias, seasonal_strength,
     signal, signal_strength, strategy_signals, updated_at)
WITH latest_futures AS (
    SELECT DISTINCT ON (ticker) *
    FROM gold.commodity_futures
    ORDER BY ticker, date DESC
),
latest_metrics AS (
    SELECT DISTINCT ON (ticker) ticker, rsi_14
    FROM gold.commodity_metrics
    ORDER BY ticker, date DESC
),
seasonality AS (
    SELECT DISTINCT ON (ticker) *
    FROM gold.commodity_seasonality
    WHERE month = EXTRACT(MONTH FROM CURRENT_DATE)::int
    ORDER BY ticker
),
next_season AS (
    SELECT DISTINCT ON (ticker) *
    FROM gold.commodity_seasonality
    WHERE month = (EXTRACT(MONTH FROM CURRENT_DATE)::int % 12) + 1
    ORDER BY ticker
)
SELECT
    f.ticker, f.name, f.category, f.exchange,
    f.close_price AS price,
    f.returns * 100 AS change_pct,
    CASE
        WHEN f.close_price > f.sma_200 THEN 'UP'
        WHEN f.close_price < f.sma_200 THEN 'DOWN'
        ELSE 'SIDEWAYS'
    END AS trend,
    ROUND(m.rsi_14::numeric, 2) AS rsi_14,
    s.seasonal_bias  AS current_month_bias,
    ns.seasonal_bias AS next_month_bias,
    ROUND(ABS(s.avg_return)::numeric, 3) AS seasonal_strength,
    CASE WHEN s.seasonal_bias = 'BULLISH' THEN 'BUY'
         WHEN s.seasonal_bias = 'BEARISH' THEN 'SELL'
         ELSE 'HOLD' END AS signal,
    ROUND(ABS(s.avg_return)::numeric, 3) AS signal_strength,
    '{}'::jsonb AS strategy_signals,
    NOW()
FROM latest_futures f
LEFT JOIN latest_metrics m  ON m.ticker = f.ticker
LEFT JOIN seasonality s     ON s.ticker = f.ticker
LEFT JOIN next_season ns    ON ns.ticker = f.ticker
ON CONFLICT (ticker) DO UPDATE SET
    price               = EXCLUDED.price,
    change_pct          = EXCLUDED.change_pct,
    trend               = EXCLUDED.trend,
    rsi_14              = EXCLUDED.rsi_14,
    current_month_bias  = EXCLUDED.current_month_bias,
    next_month_bias     = EXCLUDED.next_month_bias,
    signal              = EXCLUDED.signal,
    updated_at          = NOW();
"""

# ── Dashboard Market Overview ─────────────────────────────────────────────────

# 2026-07-04: region is now looked up from FRONTEND_INDEX_REGIONS instead of
# passed through from gold.index_metrics.region ('Americas'/'Europe'/'Asia'/
# 'Unknown', set by silver/sync_market_indices.py -- a different taxonomy for
# a different purpose, not the {US,HK} vocabulary consumption.dashboard_indices
# filters on). A prior one-off UPDATE hand-patched 5 existing rows'
# region to 'US'/'HK' directly in the DB without fixing this query; since
# ON CONFLICT is keyed on (region, index_ticker), the next run of this
# unpatched query would have re-inserted those same tickers with
# region='Americas'/'Asia' as NEW rows (no conflict match), permanently
# freezing the patched rows as stale while a duplicate, invisible-to-the-view
# row kept accumulating live data. The join below is the single source of
# truth for which tickers are in scope and what region they map to, so the
# same 5 rows get updated in place on every run and the view never mismatches.
#
# spark is populated here too (previously only ever set by that same one-off
# UPDATE, so it would never refresh again either) from this table's own
# price history, consistent with current_value's source.
DASHBOARD_OVERVIEW_SQL = """
INSERT INTO consumption.dashboard_market_overview
    (region, index_name, index_ticker,
     current_value, change_pct, change_value, change_1d, change_1w, change_1m, change_ytd,
     trend, sentiment_score, volatility_index,
     est_1d, est_1w, est_1m,
     spark, updated_at)
SELECT
    r.region,
    im.name   AS index_name,
    im.ticker AS index_ticker,
    im.close  AS current_value,
    im.change_pct,
    im.change_amount AS change_value,
    ROUND((im.change_pct)::numeric, 3)                                  AS change_1d,
    ROUND((im.returns_5d  * 100)::numeric, 3)                           AS change_1w,
    -- 21-day (monthly) return: use gold.index_metrics.returns_21d if present,
    -- else fall back to close / 21-trading-day lag over the same table so HK
    -- holiday gaps don't leave the field NULL.
    COALESCE(
        ROUND((im.returns_21d * 100)::numeric, 3),
        ROUND(((im.close / NULLIF(
            (SELECT close FROM gold.index_metrics i2
             WHERE i2.ticker = im.ticker AND i2.date <= im.date - INTERVAL '21 days'
             ORDER BY i2.date DESC LIMIT 1), 0) - 1) * 100)::numeric, 3)
    ) AS change_1m,
    -- 252-day (YTD) return: prefer returns_252d, else fall back to the
    -- latest close at least one year ago in the same series.
    COALESCE(
        ROUND((im.returns_252d * 100)::numeric, 3),
        ROUND(((im.close / NULLIF(
            (SELECT close FROM gold.index_metrics i2
             WHERE i2.ticker = im.ticker AND i2.date <= im.date - INTERVAL '252 days'
             ORDER BY i2.date DESC LIMIT 1), 0) - 1) * 100)::numeric, 3)
    ) AS change_ytd,
    CASE
        WHEN im.above_ma_200 AND im.change_pct > 0 THEN 'BULL'
        WHEN NOT im.above_ma_200 THEN 'BEAR'
        ELSE 'NEUTRAL'
    END AS trend,
    NULL::numeric AS sentiment_score,
    NULL::numeric AS volatility_index,
    CASE
        WHEN im.change_pct > 0.5 THEN 'BULLISH'
        WHEN im.change_pct < -0.5 THEN 'BEARISH'
        ELSE 'NEUTRAL'
    END AS est_1d,
    CASE
        WHEN im.above_ma_50 AND im.change_pct > 0 THEN 'BULLISH'
        WHEN NOT im.above_ma_50 THEN 'BEARISH'
        ELSE 'NEUTRAL'
    END AS est_1w,
    CASE
        WHEN im.above_ma_200 AND im.change_pct > 0 THEN 'BULLISH'
        WHEN NOT im.above_ma_200 THEN 'BEARISH'
        ELSE 'NEUTRAL'
    END AS est_1m,
    spark.values AS spark,
    NOW()
FROM (
    SELECT DISTINCT ON (ticker) *
    FROM gold.index_metrics
    ORDER BY ticker, date DESC
) im
JOIN (VALUES
    ('^GSPC', 'US'), ('^IXIC', 'US'), ('^DJI', 'US'), ('^RUT', 'US'),
    ('^HSI', 'HK')
) AS r(ticker, region) ON r.ticker = im.ticker
LEFT JOIN LATERAL (
    SELECT ARRAY_AGG(h.close ORDER BY h.date ASC) AS values
    FROM (
        SELECT close, date FROM gold.index_metrics
        WHERE ticker = im.ticker
        ORDER BY date DESC
        LIMIT 12
    ) h
) spark ON TRUE
WHERE im.is_volatility_index = FALSE
ON CONFLICT (region, index_ticker) DO UPDATE SET
    current_value  = EXCLUDED.current_value,
    change_pct     = EXCLUDED.change_pct,
    change_1d      = EXCLUDED.change_1d,
    change_1w      = EXCLUDED.change_1w,
    change_1m      = EXCLUDED.change_1m,
    change_ytd     = EXCLUDED.change_ytd,
    trend          = EXCLUDED.trend,
    est_1d         = EXCLUDED.est_1d,
    est_1w         = EXCLUDED.est_1w,
    est_1m         = EXCLUDED.est_1m,
    spark          = EXCLUDED.spark,
    updated_at     = NOW();
"""

# ── Dashboard Summary Cards ───────────────────────────────────────────────────

SUMMARY_CARDS_SQL = """
INSERT INTO consumption.dashboard_summary_cards
    (card_key, card_title, value_display, value_numeric,
     change_pct, change_display, trend, alert_level, last_updated)
-- Active positions card
SELECT
    'active_positions',
    'Active Positions',
    COUNT(*)::text,
    COUNT(*)::numeric,
    NULL, NULL, NULL, NULL, NOW()
FROM gold.paper_strategies
WHERE status = 'ACTIVE' AND quantity > 0

UNION ALL

-- Total unrealised PnL card
SELECT
    'unrealized_pnl',
    'Unrealized PnL',
    ROUND(SUM(unrealized_pnl), 2)::text || ' USD',
    ROUND(SUM(unrealized_pnl), 2),
    ROUND(AVG(unrealized_pnl_pct), 2),
    ROUND(AVG(unrealized_pnl_pct), 2)::text || '%',
    CASE WHEN SUM(unrealized_pnl) > 0 THEN 'UP' ELSE 'DOWN' END,
    CASE WHEN SUM(unrealized_pnl) < -1000 THEN 'DANGER' ELSE 'OK' END,
    NOW()
FROM gold.paper_strategies
WHERE status = 'ACTIVE'

ON CONFLICT (card_key) DO UPDATE SET
    value_display  = EXCLUDED.value_display,
    value_numeric  = EXCLUDED.value_numeric,
    change_pct     = EXCLUDED.change_pct,
    trend          = EXCLUDED.trend,
    alert_level    = EXCLUDED.alert_level,
    last_updated   = NOW();
"""

# ── Top Opportunities ─────────────────────────────────────────────────────────

OPPORTUNITIES_SQL = """
TRUNCATE consumption.dashboard_opportunities_top;

INSERT INTO consumption.dashboard_opportunities_top
    (rank, ticker, name, asset_class, signal_type, direction,
     confidence, expected_return_pct, entry_price,
     stop_loss, take_profit, rationale, updated_at)
SELECT
    ROW_NUMBER() OVER (ORDER BY sts.score DESC) AS rank,
    sts.ticker,
    ar.name,
    ar.asset_class,
    sr.strategy_id AS signal_type,
    sts.signal_action AS direction,
    ROUND(LEAST(sts.score / 100.0, 1.0), 3) AS confidence,
    ROUND(sr.sharpe_oos, 4) AS expected_return_pct,
    k.close AS entry_price,
    NULL::numeric AS stop_loss,
    NULL::numeric AS take_profit,
    sr.name AS rationale,
    NOW()
FROM gold.strategy_ticker_scores sts
LEFT JOIN gold.asset_registry ar ON ar.ticker = sts.ticker
LEFT JOIN gold.strategy_registry sr ON sr.strategy_id = sts.strategy_id
LEFT JOIN (
    SELECT DISTINCT ON (ticker) ticker, close
    FROM gold.kpis_metrics ORDER BY ticker, date DESC
) k ON k.ticker = sts.ticker
WHERE sts.signal_action = 'BUY'
ORDER BY sts.score DESC
LIMIT 10;
"""

def run():
    import time
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM gold.kpis_metrics")
    if cur.fetchone()[0] == 0:
        print("⚠️ gold.kpis_metrics empty — skipping")
        conn.close()
        return

    t0 = time.time()
    cur.execute(STOCKS_SQL)
    print(f"✅ consumption.markets_stocks_overview — {cur.rowcount} rows upserted ({time.time()-t0:.1f}s)")

    t0 = time.time()
    cur.execute(COMMODITIES_SQL)
    print(f"✅ consumption.markets_commodities_overview — {cur.rowcount} rows upserted ({time.time()-t0:.1f}s)")

    t0 = time.time()
    cur.execute(DASHBOARD_OVERVIEW_SQL)
    print(f"✅ consumption.dashboard_market_overview — {cur.rowcount} rows upserted ({time.time()-t0:.1f}s)")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    run()
