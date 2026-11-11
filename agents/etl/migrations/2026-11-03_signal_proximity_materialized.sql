-- 2026-11-03 (kanban t_30ec2517): Convert gold.v_signal_proximity from a
-- plain VIEW to a MATERIALIZED VIEW (same name, same columns).
--
-- Context: GET /api/agents/paper/signal-proximity (app/routes/agents.py:961)
-- is polled every 300s by the frontend (usePaperData.js:111,
-- SignalProximitySection.jsx:313). As a plain view the query re-plans and
-- re-executes on every poll: a 20k-row seq scan + sort over
-- silver.unified_earnings (pead_last CTE, runs twice via UNION ALL) plus a
-- 200-row window+double-sort over silver.unified_prices for the SPY 200d
-- branch. Warm ~60-150ms; cold/planning-inclusive ~1.8s (t_7213b685 audit).
-- Same incident shape as t_96e90169 (plain-view aggregate over growing
-- tables hammered by a frontend poll).
--
-- Fix: materialize the row set (1,006 rows as of 2026-11-03) and refresh it
-- via agents/etl/gold/refresh_signal_proximity_mv.py (cron
-- qr_etl.signal_proximity_mv_refresh, "40 0,9,23 * * *"):
--   00:40 UTC — CURRENT_DATE rollover (days_until_earnings, seasonal month)
--   09:40 UTC — after pipeline A 08:30 (unified_earnings, unified_prices)
--   23:40 UTC — after yf_us_postclose_topup 22:30 and regime_wf 23:15
--                 (regime_features / regime_label)
-- No consumer changes needed — same name/columns contract.
--
-- Note: last_updated (CURRENT_TIMESTAMP) is now refresh time, not query
-- time — strictly better for gold.v_etl_pipeline_health.signal_proximity_last.
--
-- Dependency handling: gold.v_etl_pipeline_health reads
-- v_signal_proximity.last_updated, so it is dropped and recreated below.

BEGIN;

DROP VIEW IF EXISTS gold.v_etl_pipeline_health;
DROP VIEW IF EXISTS gold.v_signal_proximity;

CREATE MATERIALIZED VIEW gold.v_signal_proximity AS
WITH pead_universe AS (
         SELECT DISTINCT unified_earnings.ticker
           FROM silver.unified_earnings
          WHERE unified_earnings.report_date >= CURRENT_DATE AND unified_earnings.ticker::text ~ '^[A-Z]+$'::text
        ), pead_next AS (
         SELECT ue.ticker,
            min(ue.report_date) AS next_earnings_date,
            min(ue.report_date) - CURRENT_DATE AS days_until_earnings
           FROM silver.unified_earnings ue
             JOIN pead_universe pu ON ue.ticker::text = pu.ticker::text
          WHERE ue.report_date >= CURRENT_DATE
          GROUP BY ue.ticker
        ), pead_last AS (
         SELECT DISTINCT ON (unified_earnings.ticker) unified_earnings.ticker,
            unified_earnings.eps_surprise_pct AS last_eps_surprise_pct,
            unified_earnings.price_reaction_1d AS last_price_reaction_1d
           FROM silver.unified_earnings
          WHERE unified_earnings.eps_surprise_pct IS NOT NULL
          ORDER BY unified_earnings.ticker, unified_earnings.report_date DESC
        )
 SELECT 'pead_long'::text AS strategy_id,
    p.ticker AS instrument_or_ticker,
    'earnings'::text AS signal_type,
    abs(p.days_until_earnings)::numeric AS current_value,
    0::numeric AS threshold,
    p.days_until_earnings::numeric AS distance_to_threshold,
        CASE
            WHEN p.days_until_earnings <= 0 THEN 100::numeric
            ELSE GREATEST(0::numeric, 100::numeric - (p.days_until_earnings * 5)::numeric)
        END AS distance_pct,
    p.days_until_earnings <= 0 AS signal_active,
    p.days_until_earnings AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    p.next_earnings_date,
    l.last_eps_surprise_pct,
    l.last_price_reaction_1d,
    '+5%'::text AS signal_threshold
   FROM pead_next p
     LEFT JOIN pead_last l ON p.ticker::text = l.ticker::text
UNION ALL
 SELECT 'pead_short_negative_surprise'::text AS strategy_id,
    p.ticker AS instrument_or_ticker,
    'earnings'::text AS signal_type,
    abs(p.days_until_earnings)::numeric AS current_value,
    0::numeric AS threshold,
    p.days_until_earnings::numeric AS distance_to_threshold,
        CASE
            WHEN p.days_until_earnings <= 0 THEN 100::numeric
            ELSE GREATEST(0::numeric, 100::numeric - (p.days_until_earnings * 5)::numeric)
        END AS distance_pct,
    p.days_until_earnings <= 0 AS signal_active,
    p.days_until_earnings AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    p.next_earnings_date,
    l.last_eps_surprise_pct,
    l.last_price_reaction_1d,
    '-5%'::text AS signal_threshold
   FROM pead_next p
     LEFT JOIN pead_last l ON p.ticker::text = l.ticker::text
UNION ALL
 SELECT 'vix_carry_long_equity'::text AS strategy_id,
    'VIX_CARRY'::text AS instrument_or_ticker,
    'regime'::text AS signal_type,
    rf.rv_iv_ratio::numeric AS current_value,
    0.50 AS threshold,
    (rf.rv_iv_ratio - 0.50::double precision)::numeric AS distance_to_threshold,
        CASE
            WHEN rf.rv_iv_ratio >= 0.50::double precision THEN 100::numeric
            ELSE GREATEST(0::double precision, rf.rv_iv_ratio / 0.50::double precision * 100::double precision)::numeric
        END AS distance_pct,
    rf.rv_iv_ratio >= 0.50::double precision AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    rl.regime::text AS signal_threshold
   FROM gold.regime_features rf
     JOIN gold.regime_label rl ON rf.date = rl.date
  WHERE rf.date = (( SELECT max(regime_features.date) AS max
           FROM gold.regime_features))
UNION ALL
 SELECT 'cl_cot_trend'::text AS strategy_id,
    cs.instrument AS instrument_or_ticker,
    'cot'::text AS signal_type,
    cs.cot_z::numeric AS current_value,
    1.5 AS threshold,
    1.5 - cs.cot_z AS distance_to_threshold,
        CASE
            WHEN cs.cot_z >= 1.5 THEN 100::numeric
            ELSE GREATEST(0::numeric, cs.cot_z / 1.5 * 100::numeric)
        END AS distance_pct,
    cs.cot_z >= 1.5 AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    'TREND'::text AS signal_threshold
   FROM gold.cot_sentiment cs
  WHERE cs.instrument::text = 'CL'::text AND cs.date = (( SELECT max(cot_sentiment.date) AS max
           FROM gold.cot_sentiment
          WHERE cot_sentiment.instrument::text = 'CL'::text))
UNION ALL
 SELECT
        CASE s.ticker
            WHEN 'CL=F'::text THEN 'crude_seasonal'::text
            WHEN 'NG=F'::text THEN 'natgas_seasonal'::text
            WHEN 'GC=F'::text THEN 'gold_seasonal'::text
            ELSE NULL::text
        END AS strategy_id,
    s.ticker AS instrument_or_ticker,
    'calendar'::text AS signal_type,
    EXTRACT(month FROM CURRENT_DATE) AS current_value,
    NULL::numeric AS threshold,
    NULL::numeric AS distance_to_threshold,
        CASE
            WHEN s.seasonal_bias::text <> 'neutral'::text THEN 100::numeric
            ELSE 0::numeric
        END AS distance_pct,
    s.seasonal_bias::text <> 'neutral'::text AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    s.seasonal_bias::text AS signal_threshold
   FROM gold.commodity_seasonality s
  WHERE (s.ticker::text = ANY (ARRAY['CL=F'::character varying, 'NG=F'::character varying, 'GC=F'::character varying]::text[])) AND s.month::numeric = EXTRACT(month FROM CURRENT_DATE)
UNION ALL
 SELECT 'spy_200d_reclaim_long'::text AS strategy_id,
    'SPY'::text AS instrument_or_ticker,
    'regime_transition'::text AS signal_type,
    spy.pct_from_200d AS current_value,
    0::numeric AS threshold,
    - spy.pct_from_200d AS distance_to_threshold,
        CASE
            WHEN spy.pct_from_200d >= 0::numeric THEN 100::numeric
            ELSE GREATEST(0::numeric, 100::numeric + spy.pct_from_200d)
        END AS distance_pct,
    spy.pct_from_200d >= 0::numeric AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    'above_200d'::text AS signal_threshold
   FROM ( SELECT unified_prices.date,
            unified_prices.close,
            avg(unified_prices.close) OVER (ORDER BY unified_prices.date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma200,
            (unified_prices.close - avg(unified_prices.close) OVER (ORDER BY unified_prices.date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)) / NULLIF(unified_prices.close, 0::numeric) * 100::numeric AS pct_from_200d
           FROM silver.unified_prices
          WHERE unified_prices.ticker::text = 'SPY'::text AND unified_prices.close IS NOT NULL
          ORDER BY unified_prices.date DESC
         LIMIT 1) spy;

-- (strategy_id, instrument_or_ticker) is unique across all six branches
-- (verified on live data 2026-11-03: 1,006 rows, 0 dupes); enables
-- REFRESH MATERIALIZED VIEW CONCURRENTLY.
CREATE UNIQUE INDEX idx_v_signal_proximity_uq
    ON gold.v_signal_proximity (strategy_id, instrument_or_ticker);

-- Recreate the dependent pipeline-health view (references
-- v_signal_proximity.last_updated as signal_proximity_last).
CREATE VIEW gold.v_etl_pipeline_health AS
WITH pipeline_a AS (
         SELECT 'Pipeline A — Ingestion'::text AS pipeline,
            ( SELECT max(unified_prices.date) AS max
                   FROM silver.unified_prices) AS unified_prices_last,
            ( SELECT max(unified_earnings.report_date) AS max
                   FROM silver.unified_earnings) AS earnings_last,
            ( SELECT max(fred_macro_indicators.date) AS max
                   FROM bronze.fred_macro_indicators) AS fred_last,
            ( SELECT max(binance_crypto_ohlcv."timestamp"::date) AS max
                   FROM bronze.binance_crypto_ohlcv) AS binance_last,
            ( SELECT max(ibkr_positions_live.fetched_at::date) AS max
                   FROM bronze.ibkr_positions_live) AS ibkr_positions_last,
            ( SELECT max(ibkr_account_summary.fetched_at::date) AS max
                   FROM bronze.ibkr_account_summary) AS ibkr_account_last,
            ( SELECT max(yf_prices.date) AS max
                   FROM bronze.yf_prices) AS yf_prices_last,
            ( SELECT max(yf_commodity_futures.date) AS max
                   FROM bronze.yf_commodity_futures) AS commodity_futures_last,
            ( SELECT max(institutional_holdings.report_date) AS max
                   FROM bronze.institutional_holdings) AS institutional_holdings_last
        ), pipeline_b AS (
         SELECT 'Pipeline B — Signals'::text AS pipeline,
            ( SELECT max(regime_features.date) AS max
                   FROM gold.regime_features) AS regime_features_last,
            ( SELECT max(regime_label.date) AS max
                   FROM gold.regime_label) AS regime_label_last,
            ( SELECT max(cot_sentiment.date) AS max
                   FROM gold.cot_sentiment) AS cot_last,
            ( SELECT max(macro_event_flags.date) AS max
                   FROM gold.macro_event_flags) AS macro_flags_last,
            ( SELECT max(hmm_regime_states.date) AS max
                   FROM gold.hmm_regime_states) AS hmm_states_last,
            ( SELECT max(crypto_funding_metrics.date) AS max
                   FROM gold.crypto_funding_metrics) AS crypto_funding_last,
            ( SELECT max(earnings_signals.earnings_date) AS max
                   FROM gold.earnings_signals) AS earnings_signals_last,
            ( SELECT max(stock_metrics.date) AS max
                   FROM gold.stock_metrics) AS stock_metrics_last,
            ( SELECT max(stock_metrics_history.date) AS max
                   FROM gold.stock_metrics_history) AS stock_metrics_history_last,
            ( SELECT max(kpis_metrics.date) AS max
                   FROM gold.kpis_metrics) AS kpis_last,
            ( SELECT max(daily_ohlcv.date) AS max
                   FROM gold.daily_ohlcv) AS daily_ohlcv_last,
            ( SELECT max(vix_regime.date) AS max
                   FROM gold.vix_regime) AS vix_regime_last,
            ( SELECT max(strategy_signals.date) AS max
                   FROM gold.strategy_signals) AS strategy_signals_last,
            ( SELECT max(crypto_kpis.date) AS max
                   FROM gold.crypto_kpis) AS crypto_kpis_last,
            ( SELECT max(crypto_metrics.date) AS max
                   FROM gold.crypto_metrics) AS crypto_metrics_last,
            ( SELECT max(commodity_futures.date) AS max
                   FROM gold.commodity_futures) AS gold_commodity_futures_last,
            ( SELECT max(commodity_metrics.date) AS max
                   FROM gold.commodity_metrics) AS commodity_metrics_last,
            ( SELECT max(fx_metrics.date) AS max
                   FROM gold.fx_metrics) AS fx_metrics_last,
            ( SELECT max(index_metrics.date) AS max
                   FROM gold.index_metrics) AS index_metrics_last,
            ( SELECT max(market_regimes."timestamp"::date) AS max
                   FROM gold.market_regimes) AS market_regimes_last,
            ( SELECT max(market_sentiment_daily.date) AS max
                   FROM gold.market_sentiment_daily) AS market_sentiment_last,
            ( SELECT max(ibkr_positions_live.fetched_at::date) AS max
                   FROM gold.ibkr_positions_live) AS gold_ibkr_positions_last,
            ( SELECT max(ibkr_account_summary.fetched_at::date) AS max
                   FROM gold.ibkr_account_summary) AS gold_ibkr_account_last,
            ( SELECT max(earnings_data.report_date) AS max
                   FROM gold.earnings_data) AS earnings_data_last,
            ( SELECT max(sue_scores.report_date) AS max
                   FROM gold.sue_scores) AS sue_scores_last,
            ( SELECT max(strategy_ticker_scores.updated_at::date) AS max
                   FROM gold.strategy_ticker_scores) AS strategy_ticker_scores_last,
            ( SELECT max(strategy_backtests.run_date) AS max
                   FROM gold.strategy_backtests) AS strategy_backtests_last,
            ( SELECT max(strategy_registry.updated_at::date) AS max
                   FROM gold.strategy_registry) AS strategy_registry_last,
            ( SELECT max(portfolio_snapshots.snapshot_date) AS max
                   FROM gold.portfolio_snapshots) AS portfolio_snapshots_last,
            ( SELECT max(paper_strategies.updated_at::date) AS max
                   FROM gold.paper_strategies) AS paper_strategies_last,
            ( SELECT max(positions.updated_at::date) AS max
                   FROM gold.positions) AS positions_last,
            ( SELECT max(trade_executions.executed_at::date) AS max
                   FROM gold.trade_executions) AS trade_executions_last,
            ( SELECT max(hft_metrics.date) AS max
                   FROM gold.hft_metrics) AS hft_metrics_last,
            ( SELECT max(v_signal_proximity.last_updated::date) AS max
                   FROM gold.v_signal_proximity) AS signal_proximity_last,
            ( SELECT max(s9_macd_signals.signal_date) AS max
                   FROM gold.s9_macd_signals) AS s9_signals_last,
            ( SELECT max(s9_paper_trades.entry_date) AS max
                   FROM gold.s9_paper_trades) AS s9_trades_last,
            ( SELECT max(seasonality_patterns.calculated_at::date) AS max
                   FROM gold.seasonality_patterns) AS seasonality_last,
            ( SELECT max(hk_ipo_calendar.listing_date) AS max
                   FROM gold.hk_ipo_calendar) AS hk_ipo_last,
            ( SELECT max(commodity_seasonality.calculated_at::date) AS max
                   FROM gold.commodity_seasonality) AS commodity_seasonality_last,
            ( SELECT max(asset_registry.updated_at::date) AS max
                   FROM gold.asset_registry) AS asset_registry_last
        )
 SELECT 'Pipeline A'::text AS pipeline,
    pipeline_a.unified_prices_last,
    pipeline_a.earnings_last,
    pipeline_a.fred_last,
    pipeline_a.binance_last,
    pipeline_a.ibkr_positions_last,
    pipeline_a.ibkr_account_last,
    pipeline_a.yf_prices_last,
    pipeline_a.commodity_futures_last,
    pipeline_a.institutional_holdings_last,
    NULL::date AS regime_features_last,
    NULL::date AS regime_label_last,
    NULL::date AS cot_last,
    NULL::date AS macro_flags_last,
    NULL::date AS hmm_states_last,
    NULL::date AS crypto_funding_last,
    NULL::date AS earnings_signals_last,
    NULL::date AS stock_metrics_last,
    NULL::date AS stock_metrics_history_last,
    NULL::date AS kpis_last,
    NULL::date AS daily_ohlcv_last,
    NULL::date AS vix_regime_last,
    NULL::date AS strategy_signals_last,
    NULL::date AS crypto_kpis_last,
    NULL::date AS crypto_metrics_last,
    NULL::date AS gold_commodity_futures_last,
    NULL::date AS commodity_metrics_last,
    NULL::date AS fx_metrics_last,
    NULL::date AS index_metrics_last,
    NULL::date AS market_regimes_last,
    NULL::date AS market_sentiment_last,
    NULL::date AS gold_ibkr_positions_last,
    NULL::date AS gold_ibkr_account_last,
    NULL::date AS earnings_data_last,
    NULL::date AS sue_scores_last,
    NULL::date AS strategy_ticker_scores_last,
    NULL::date AS strategy_backtests_last,
    NULL::date AS strategy_registry_last,
    NULL::date AS portfolio_snapshots_last,
    NULL::date AS paper_strategies_last,
    NULL::date AS positions_last,
    NULL::date AS trade_executions_last,
    NULL::date AS hft_metrics_last,
    NULL::date AS signal_proximity_last,
    NULL::date AS s9_signals_last,
    NULL::date AS s9_trades_last,
    NULL::date AS seasonality_last,
    NULL::date AS hk_ipo_last,
    NULL::date AS commodity_seasonality_last,
    NULL::date AS asset_registry_last,
        CASE
            WHEN pipeline_a.unified_prices_last < (CURRENT_DATE - 2) THEN 'STALE'::text
            WHEN pipeline_a.earnings_last < (CURRENT_DATE - 2) THEN 'STALE'::text
            WHEN pipeline_a.fred_last < (CURRENT_DATE - 35) THEN 'STALE'::text
            WHEN pipeline_a.binance_last < (CURRENT_DATE - 1) THEN 'STALE'::text
            WHEN pipeline_a.ibkr_positions_last < (CURRENT_DATE - 2) THEN 'STALE'::text
            ELSE 'OK'::text
        END AS status
   FROM pipeline_a
UNION ALL
 SELECT 'Pipeline B'::text AS pipeline,
    NULL::date AS unified_prices_last,
    NULL::date AS earnings_last,
    NULL::date AS fred_last,
    NULL::date AS binance_last,
    NULL::date AS ibkr_positions_last,
    NULL::date AS ibkr_account_last,
    NULL::date AS yf_prices_last,
    NULL::date AS commodity_futures_last,
    NULL::date AS institutional_holdings_last,
    pipeline_b.regime_features_last,
    pipeline_b.regime_label_last,
    pipeline_b.cot_last,
    pipeline_b.macro_flags_last,
    pipeline_b.hmm_states_last,
    pipeline_b.crypto_funding_last,
    pipeline_b.earnings_signals_last,
    pipeline_b.stock_metrics_last,
    pipeline_b.stock_metrics_history_last,
    pipeline_b.kpis_last,
    pipeline_b.daily_ohlcv_last,
    pipeline_b.vix_regime_last,
    pipeline_b.strategy_signals_last,
    pipeline_b.crypto_kpis_last,
    pipeline_b.crypto_metrics_last,
    pipeline_b.gold_commodity_futures_last,
    pipeline_b.commodity_metrics_last,
    pipeline_b.fx_metrics_last,
    pipeline_b.index_metrics_last,
    pipeline_b.market_regimes_last,
    pipeline_b.market_sentiment_last,
    pipeline_b.gold_ibkr_positions_last,
    pipeline_b.gold_ibkr_account_last,
    pipeline_b.earnings_data_last,
    pipeline_b.sue_scores_last,
    pipeline_b.strategy_ticker_scores_last,
    pipeline_b.strategy_backtests_last,
    pipeline_b.strategy_registry_last,
    pipeline_b.portfolio_snapshots_last,
    pipeline_b.paper_strategies_last,
    pipeline_b.positions_last,
    pipeline_b.trade_executions_last,
    pipeline_b.hft_metrics_last,
    pipeline_b.signal_proximity_last,
    pipeline_b.s9_signals_last,
    pipeline_b.s9_trades_last,
    pipeline_b.seasonality_last,
    pipeline_b.hk_ipo_last,
    pipeline_b.commodity_seasonality_last,
    pipeline_b.asset_registry_last,
        CASE
            WHEN pipeline_b.regime_features_last < (CURRENT_DATE - 2) THEN 'STALE'::text
            WHEN pipeline_b.regime_label_last < (CURRENT_DATE - 2) THEN 'STALE'::text
            WHEN pipeline_b.stock_metrics_last < (CURRENT_DATE - 2) THEN 'STALE'::text
            WHEN pipeline_b.kpis_last < (CURRENT_DATE - 2) THEN 'STALE'::text
            ELSE 'OK'::text
        END AS status
   FROM pipeline_b;

COMMIT;
