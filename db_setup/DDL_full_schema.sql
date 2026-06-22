--
-- PostgreSQL database dump
--

\restrict uxhuJhtme8CfCW3enj1ri3U0mG4rE0BF6efKrONXiWJsSJqvKuMyAMdyfccVOv0

-- Dumped from database version 17.9
-- Dumped by pg_dump version 18.4 (Ubuntu 18.4-0ubuntu0.26.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

ALTER TABLE IF EXISTS ONLY gold.strategy_universes DROP CONSTRAINT IF EXISTS strategy_universes_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_ticker_scores DROP CONSTRAINT IF EXISTS strategy_ticker_scores_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_thresholds DROP CONSTRAINT IF EXISTS strategy_thresholds_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_signal_criteria DROP CONSTRAINT IF EXISTS strategy_signal_criteria_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_risk_reviews DROP CONSTRAINT IF EXISTS strategy_risk_reviews_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_risk_reviews DROP CONSTRAINT IF EXISTS strategy_risk_reviews_run_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_research DROP CONSTRAINT IF EXISTS strategy_research_parent_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_registry DROP CONSTRAINT IF EXISTS strategy_registry_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_qa_reviews DROP CONSTRAINT IF EXISTS strategy_qa_reviews_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_qa_reviews DROP CONSTRAINT IF EXISTS strategy_qa_reviews_run_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_performance_log DROP CONSTRAINT IF EXISTS strategy_performance_log_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_configs DROP CONSTRAINT IF EXISTS strategy_configs_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_backtest_trades DROP CONSTRAINT IF EXISTS strategy_backtest_trades_run_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_backtest_runs DROP CONSTRAINT IF EXISTS strategy_backtest_runs_strategy_id_fkey;
ALTER TABLE IF EXISTS ONLY gold.s9_paper_trades DROP CONSTRAINT IF EXISTS s9_paper_trades_signal_id_fkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_historical_bars DROP CONSTRAINT IF EXISTS ibkr_historical_bars_con_id_fkey;
DROP TRIGGER IF EXISTS trg_strategy_ticker_scores_updated ON gold.strategy_ticker_scores;
DROP TRIGGER IF EXISTS trg_strategy_research_updated ON gold.strategy_research;
DROP TRIGGER IF EXISTS trg_strategy_registry_updated ON gold.strategy_registry;
DROP INDEX IF EXISTS silver.idx_tech_ind_ticker_date;
DROP INDEX IF EXISTS silver.idx_silver_asset_class;
DROP INDEX IF EXISTS silver.idx_market_indices_ticker_date;
DROP INDEX IF EXISTS research_sandbox.idx_strategy_ideas_date;
DROP INDEX IF EXISTS research_sandbox.idx_daily_rca_market;
DROP INDEX IF EXISTS research_sandbox.idx_daily_rca_date;
DROP INDEX IF EXISTS gold.uq_paper_run_log_date_type;
DROP INDEX IF EXISTS gold.ix_fx_metrics_ticker_date;
DROP INDEX IF EXISTS gold.ix_crypto_metrics_ticker_date;
DROP INDEX IF EXISTS gold.ix_comm_metrics_ticker_date;
DROP INDEX IF EXISTS gold.idx_sue_ticker;
DROP INDEX IF EXISTS gold.idx_sue_decile;
DROP INDEX IF EXISTS gold.idx_sue_date;
DROP INDEX IF EXISTS gold.idx_su_strategy;
DROP INDEX IF EXISTS gold.idx_sts_strategy;
DROP INDEX IF EXISTS gold.idx_sts_action;
DROP INDEX IF EXISTS gold.idx_strategy_definitions_execution_mode;
DROP INDEX IF EXISTS gold.idx_stock_metrics_new_ticker_date;
DROP INDEX IF EXISTS gold.idx_stock_metrics_new_sector;
DROP INDEX IF EXISTS gold.idx_stock_metrics_new_date;
DROP INDEX IF EXISTS gold.idx_ssc_strategy;
DROP INDEX IF EXISTS gold.idx_srr_strategy;
DROP INDEX IF EXISTS gold.idx_srr_decision;
DROP INDEX IF EXISTS gold.idx_sreg_status;
DROP INDEX IF EXISTS gold.idx_sreg_asset;
DROP INDEX IF EXISTS gold.idx_sr_status;
DROP INDEX IF EXISTS gold.idx_sr_parent;
DROP INDEX IF EXISTS gold.idx_sr_created;
DROP INDEX IF EXISTS gold.idx_sr_asset;
DROP INDEX IF EXISTS gold.idx_sqr_strategy;
DROP INDEX IF EXISTS gold.idx_sqr_decision;
DROP INDEX IF EXISTS gold.idx_spl_strategy;
DROP INDEX IF EXISTS gold.idx_spl_date;
DROP INDEX IF EXISTS gold.idx_smh_ticker_date;
DROP INDEX IF EXISTS gold.idx_smh_sector_date;
DROP INDEX IF EXISTS gold.idx_smh_date;
DROP INDEX IF EXISTS gold.idx_sbt_strategy;
DROP INDEX IF EXISTS gold.idx_sbt_run;
DROP INDEX IF EXISTS gold.idx_sbt_period;
DROP INDEX IF EXISTS gold.idx_sbr_strategy;
DROP INDEX IF EXISTS gold.idx_sbr_passed;
DROP INDEX IF EXISTS gold.idx_sbr_created;
DROP INDEX IF EXISTS gold.idx_s9_trades_strategy;
DROP INDEX IF EXISTS gold.idx_s9_trades_status;
DROP INDEX IF EXISTS gold.idx_s9_signals_ticker;
DROP INDEX IF EXISTS gold.idx_s9_signals_date;
DROP INDEX IF EXISTS gold.idx_s9_signals_active;
DROP INDEX IF EXISTS gold.idx_regime_features_date;
DROP INDEX IF EXISTS gold.idx_paper_trades_ts_closed;
DROP INDEX IF EXISTS gold.idx_paper_trades_strategy;
DROP INDEX IF EXISTS gold.idx_paper_trades_status;
DROP INDEX IF EXISTS gold.idx_paper_run_log_date;
DROP INDEX IF EXISTS gold.idx_kpis_ticker_date_desc;
DROP INDEX IF EXISTS gold.idx_inst_holdings_ticker;
DROP INDEX IF EXISTS gold.idx_im_ticker_date;
DROP INDEX IF EXISTS gold.idx_im_date;
DROP INDEX IF EXISTS gold.idx_ibkr_orders_strategy;
DROP INDEX IF EXISTS gold.idx_gold_vix_regime_date;
DROP INDEX IF EXISTS gold.idx_gold_macro_event_date;
DROP INDEX IF EXISTS gold.idx_gold_daily_ohlcv_date;
DROP INDEX IF EXISTS gold.idx_gold_daily_ohlcv_asset;
DROP INDEX IF EXISTS gold.idx_gold_crypto_funding_date;
DROP INDEX IF EXISTS gold.idx_gold_cot_date;
DROP INDEX IF EXISTS gold.idx_futures_ticker;
DROP INDEX IF EXISTS gold.idx_futures_date;
DROP INDEX IF EXISTS gold.idx_futures_category;
DROP INDEX IF EXISTS gold.idx_equities_kpis_ticker;
DROP INDEX IF EXISTS gold.idx_equities_kpis_date;
DROP INDEX IF EXISTS gold.idx_earnings_ticker;
DROP INDEX IF EXISTS gold.idx_earnings_date;
DROP INDEX IF EXISTS gold.idx_commodity_futures_ticker_date_desc;
DROP INDEX IF EXISTS gold.idx_agent_events_strategy;
DROP INDEX IF EXISTS gold.idx_agent_events_source;
DROP INDEX IF EXISTS gold.idx_agent_events_created;
DROP INDEX IF EXISTS consumption.idx_scores_updated;
DROP INDEX IF EXISTS consumption.idx_rp_updated;
DROP INDEX IF EXISTS consumption.idx_commodities_timestamp;
DROP INDEX IF EXISTS bronze.idx_ih_date;
DROP INDEX IF EXISTS bronze.idx_ibkr_orders_ticker;
DROP INDEX IF EXISTS bronze.idx_ibkr_orders_status;
DROP INDEX IF EXISTS bronze.idx_ibkr_orders_fetched_at;
DROP INDEX IF EXISTS bronze.idx_ibkr_orders_account;
DROP INDEX IF EXISTS bronze.idx_ec_ticker;
DROP INDEX IF EXISTS bronze.idx_ec_date;
DROP INDEX IF EXISTS bronze.idx_dql_source;
ALTER TABLE IF EXISTS ONLY silver.vix_indicators DROP CONSTRAINT IF EXISTS vix_indicators_pkey;
ALTER TABLE IF EXISTS ONLY silver.unified_prices DROP CONSTRAINT IF EXISTS unified_prices_new_ticker_date_key;
ALTER TABLE IF EXISTS ONLY silver.unified_prices DROP CONSTRAINT IF EXISTS unified_prices_new_pkey;
ALTER TABLE IF EXISTS ONLY silver.unified_ipo_performance DROP CONSTRAINT IF EXISTS unified_ipo_performance_pkey;
ALTER TABLE IF EXISTS ONLY silver.unified_ipo_calendar DROP CONSTRAINT IF EXISTS unified_ipo_calendar_ticker_listing_date_key;
ALTER TABLE IF EXISTS ONLY silver.unified_ipo_calendar DROP CONSTRAINT IF EXISTS unified_ipo_calendar_pkey;
ALTER TABLE IF EXISTS ONLY silver.unified_earnings DROP CONSTRAINT IF EXISTS unified_earnings_ticker_report_date_key;
ALTER TABLE IF EXISTS ONLY silver.unified_earnings DROP CONSTRAINT IF EXISTS unified_earnings_pkey;
ALTER TABLE IF EXISTS ONLY silver.technical_indicators DROP CONSTRAINT IF EXISTS technical_indicators_ticker_date_key;
ALTER TABLE IF EXISTS ONLY silver.technical_indicators DROP CONSTRAINT IF EXISTS technical_indicators_pkey;
ALTER TABLE IF EXISTS ONLY silver.quarantine DROP CONSTRAINT IF EXISTS quarantine_pkey;
ALTER TABLE IF EXISTS ONLY silver.market_indices DROP CONSTRAINT IF EXISTS market_indices_ticker_date_key;
ALTER TABLE IF EXISTS ONLY silver.market_indices DROP CONSTRAINT IF EXISTS market_indices_pkey;
ALTER TABLE IF EXISTS ONLY silver.macro_event_calendar DROP CONSTRAINT IF EXISTS macro_event_calendar_pkey;
ALTER TABLE IF EXISTS ONLY silver.historical_stock_data DROP CONSTRAINT IF EXISTS historical_stock_data_ticker_date_key;
ALTER TABLE IF EXISTS ONLY silver.historical_stock_data DROP CONSTRAINT IF EXISTS historical_stock_data_pkey;
ALTER TABLE IF EXISTS ONLY silver.historical_news DROP CONSTRAINT IF EXISTS historical_news_pkey;
ALTER TABLE IF EXISTS ONLY silver.historical_news DROP CONSTRAINT IF EXISTS historical_news_date_entity_name_headline_key;
ALTER TABLE IF EXISTS ONLY silver.funding_rates_daily DROP CONSTRAINT IF EXISTS funding_rates_daily_pkey;
ALTER TABLE IF EXISTS ONLY silver.earnings_calendar DROP CONSTRAINT IF EXISTS earnings_calendar_report_date_ticker_key;
ALTER TABLE IF EXISTS ONLY silver.earnings_calendar DROP CONSTRAINT IF EXISTS earnings_calendar_pkey;
ALTER TABLE IF EXISTS ONLY silver.crypto_ohlcv_normalized DROP CONSTRAINT IF EXISTS crypto_ohlcv_normalized_symbol_interval_timestamp_key;
ALTER TABLE IF EXISTS ONLY silver.crypto_ohlcv_normalized DROP CONSTRAINT IF EXISTS crypto_ohlcv_normalized_pkey;
ALTER TABLE IF EXISTS ONLY silver.cot_euro_fx_daily DROP CONSTRAINT IF EXISTS cot_euro_fx_daily_pkey;
ALTER TABLE IF EXISTS ONLY silver.asset_registry DROP CONSTRAINT IF EXISTS asset_registry_ticker_key;
ALTER TABLE IF EXISTS ONLY silver.asset_registry DROP CONSTRAINT IF EXISTS asset_registry_pkey;
ALTER TABLE IF EXISTS ONLY shared.agent_tasks DROP CONSTRAINT IF EXISTS agent_tasks_pkey;
ALTER TABLE IF EXISTS ONLY research_sandbox.vix_data DROP CONSTRAINT IF EXISTS vix_data_pkey;
ALTER TABLE IF EXISTS ONLY research_sandbox.ticker_sectors DROP CONSTRAINT IF EXISTS ticker_sectors_pkey;
ALTER TABLE IF EXISTS ONLY research_sandbox.spy_ohlcv DROP CONSTRAINT IF EXISTS spy_ohlcv_pkey;
ALTER TABLE IF EXISTS ONLY research_sandbox.research_log DROP CONSTRAINT IF EXISTS research_log_pkey;
ALTER TABLE IF EXISTS ONLY research_sandbox.daily_strategy_ideas DROP CONSTRAINT IF EXISTS daily_strategy_ideas_pkey;
ALTER TABLE IF EXISTS ONLY research_sandbox.daily_market_rca DROP CONSTRAINT IF EXISTS daily_market_rca_pkey;
ALTER TABLE IF EXISTS ONLY research_sandbox.daily_market_rca DROP CONSTRAINT IF EXISTS daily_market_rca_date_market_ticker_key;
ALTER TABLE IF EXISTS ONLY research_sandbox.benchmark_indices DROP CONSTRAINT IF EXISTS benchmark_indices_pkey;
ALTER TABLE IF EXISTS ONLY openclaw_researcher.gold_layer_state DROP CONSTRAINT IF EXISTS gold_layer_state_pkey;
ALTER TABLE IF EXISTS ONLY gold.vix_regime DROP CONSTRAINT IF EXISTS vix_regime_pkey;
ALTER TABLE IF EXISTS ONLY gold.ibkr_orders DROP CONSTRAINT IF EXISTS uk_ibkr_orders_account_order_id;
ALTER TABLE IF EXISTS ONLY gold.trade_executions DROP CONSTRAINT IF EXISTS trade_executions_pkey;
ALTER TABLE IF EXISTS ONLY gold.system_config DROP CONSTRAINT IF EXISTS system_config_pkey;
ALTER TABLE IF EXISTS ONLY gold.system_config DROP CONSTRAINT IF EXISTS system_config_component_key_key;
ALTER TABLE IF EXISTS ONLY gold.sync_schedules DROP CONSTRAINT IF EXISTS sync_schedules_pkey;
ALTER TABLE IF EXISTS ONLY gold.sync_schedules DROP CONSTRAINT IF EXISTS sync_schedules_component_key;
ALTER TABLE IF EXISTS ONLY gold.sue_scores DROP CONSTRAINT IF EXISTS sue_scores_ticker_report_date_key;
ALTER TABLE IF EXISTS ONLY gold.sue_scores DROP CONSTRAINT IF EXISTS sue_scores_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_universes DROP CONSTRAINT IF EXISTS strategy_universes_strategy_id_ticker_key;
ALTER TABLE IF EXISTS ONLY gold.strategy_universes DROP CONSTRAINT IF EXISTS strategy_universes_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_ticker_scores DROP CONSTRAINT IF EXISTS strategy_ticker_scores_strategy_id_ticker_key;
ALTER TABLE IF EXISTS ONLY gold.strategy_ticker_scores DROP CONSTRAINT IF EXISTS strategy_ticker_scores_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_thresholds DROP CONSTRAINT IF EXISTS strategy_thresholds_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_templates DROP CONSTRAINT IF EXISTS strategy_templates_template_id_key;
ALTER TABLE IF EXISTS ONLY gold.strategy_templates DROP CONSTRAINT IF EXISTS strategy_templates_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_signals DROP CONSTRAINT IF EXISTS strategy_signals_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_signal_criteria DROP CONSTRAINT IF EXISTS strategy_signal_criteria_strategy_id_signal_type_criterion__key;
ALTER TABLE IF EXISTS ONLY gold.strategy_signal_criteria DROP CONSTRAINT IF EXISTS strategy_signal_criteria_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_risk_reviews DROP CONSTRAINT IF EXISTS strategy_risk_reviews_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_research DROP CONSTRAINT IF EXISTS strategy_research_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_registry DROP CONSTRAINT IF EXISTS strategy_registry_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_qa_reviews DROP CONSTRAINT IF EXISTS strategy_qa_reviews_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_performance_log DROP CONSTRAINT IF EXISTS strategy_performance_log_strategy_id_log_date_key;
ALTER TABLE IF EXISTS ONLY gold.strategy_performance_log DROP CONSTRAINT IF EXISTS strategy_performance_log_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_definitions DROP CONSTRAINT IF EXISTS strategy_definitions_strategy_id_key;
ALTER TABLE IF EXISTS ONLY gold.strategy_definitions DROP CONSTRAINT IF EXISTS strategy_definitions_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_configs DROP CONSTRAINT IF EXISTS strategy_configs_strategy_id_config_key_key;
ALTER TABLE IF EXISTS ONLY gold.strategy_configs DROP CONSTRAINT IF EXISTS strategy_configs_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_backtests DROP CONSTRAINT IF EXISTS strategy_backtests_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_backtest_trades DROP CONSTRAINT IF EXISTS strategy_backtest_trades_pkey;
ALTER TABLE IF EXISTS ONLY gold.strategy_backtest_runs DROP CONSTRAINT IF EXISTS strategy_backtest_runs_pkey;
ALTER TABLE IF EXISTS ONLY gold.stock_metrics_new DROP CONSTRAINT IF EXISTS stock_metrics_new_pkey;
ALTER TABLE IF EXISTS ONLY gold.stock_metrics_history DROP CONSTRAINT IF EXISTS stock_metrics_history_pkey;
ALTER TABLE IF EXISTS ONLY gold.signal_cancellations DROP CONSTRAINT IF EXISTS signal_cancellations_pkey;
ALTER TABLE IF EXISTS ONLY gold.sentiment_mart DROP CONSTRAINT IF EXISTS sentiment_mart_pkey;
ALTER TABLE IF EXISTS ONLY gold.sentiment_mart DROP CONSTRAINT IF EXISTS sentiment_mart_date_entity_name_key;
ALTER TABLE IF EXISTS ONLY gold.sector_etfs DROP CONSTRAINT IF EXISTS sector_etfs_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.sector_etfs DROP CONSTRAINT IF EXISTS sector_etfs_pkey;
ALTER TABLE IF EXISTS ONLY gold.seasonality_patterns DROP CONSTRAINT IF EXISTS seasonality_patterns_ticker_month_key;
ALTER TABLE IF EXISTS ONLY gold.seasonality_patterns DROP CONSTRAINT IF EXISTS seasonality_patterns_pkey;
ALTER TABLE IF EXISTS ONLY gold.s9_paper_trades DROP CONSTRAINT IF EXISTS s9_paper_trades_pkey;
ALTER TABLE IF EXISTS ONLY gold.s9_macd_signals DROP CONSTRAINT IF EXISTS s9_macd_signals_strategy_id_ticker_signal_date_key;
ALTER TABLE IF EXISTS ONLY gold.s9_macd_signals DROP CONSTRAINT IF EXISTS s9_macd_signals_pkey;
ALTER TABLE IF EXISTS ONLY gold.regime_label DROP CONSTRAINT IF EXISTS regime_label_pkey;
ALTER TABLE IF EXISTS ONLY gold.regime_features DROP CONSTRAINT IF EXISTS regime_features_pkey;
ALTER TABLE IF EXISTS ONLY gold.positions DROP CONSTRAINT IF EXISTS positions_pkey;
ALTER TABLE IF EXISTS ONLY gold.portfolio_snapshots DROP CONSTRAINT IF EXISTS portfolio_snapshots_snapshot_date_portfolio_type_key;
ALTER TABLE IF EXISTS ONLY gold.portfolio_snapshots DROP CONSTRAINT IF EXISTS portfolio_snapshots_pkey;
ALTER TABLE IF EXISTS ONLY gold.platform_settings DROP CONSTRAINT IF EXISTS platform_settings_pkey;
ALTER TABLE IF EXISTS ONLY gold.paper_trades DROP CONSTRAINT IF EXISTS paper_trades_pkey;
ALTER TABLE IF EXISTS ONLY gold.paper_strategies DROP CONSTRAINT IF EXISTS paper_strategies_strategy_id_key;
ALTER TABLE IF EXISTS ONLY gold.paper_strategies DROP CONSTRAINT IF EXISTS paper_strategies_pkey;
ALTER TABLE IF EXISTS ONLY gold.paper_run_log DROP CONSTRAINT IF EXISTS paper_run_log_pkey;
ALTER TABLE IF EXISTS ONLY gold.nfp_equity_drift_backtests DROP CONSTRAINT IF EXISTS nfp_equity_drift_backtests_strategy_name_version_backtest_d_key;
ALTER TABLE IF EXISTS ONLY gold.nfp_equity_drift_backtests DROP CONSTRAINT IF EXISTS nfp_equity_drift_backtests_pkey;
ALTER TABLE IF EXISTS ONLY gold.metric_definitions DROP CONSTRAINT IF EXISTS metric_definitions_pkey;
ALTER TABLE IF EXISTS ONLY gold.market_sentiment_daily DROP CONSTRAINT IF EXISTS market_sentiment_daily_pkey;
ALTER TABLE IF EXISTS ONLY gold.market_sentiment_daily DROP CONSTRAINT IF EXISTS market_sentiment_daily_market_date_key;
ALTER TABLE IF EXISTS ONLY gold.market_regimes DROP CONSTRAINT IF EXISTS market_regimes_pkey;
ALTER TABLE IF EXISTS ONLY gold.macro_indicators DROP CONSTRAINT IF EXISTS macro_indicators_pkey;
ALTER TABLE IF EXISTS ONLY gold.macro_indicators DROP CONSTRAINT IF EXISTS macro_indicators_date_indicator_name_key;
ALTER TABLE IF EXISTS ONLY gold.macro_event_flags DROP CONSTRAINT IF EXISTS macro_event_flags_pkey;
ALTER TABLE IF EXISTS ONLY gold.llm_key_entities_config DROP CONSTRAINT IF EXISTS key_entities_config_pkey;
ALTER TABLE IF EXISTS ONLY gold.llm_key_entities_config DROP CONSTRAINT IF EXISTS key_entities_config_name_key;
ALTER TABLE IF EXISTS ONLY gold.interbank_rates DROP CONSTRAINT IF EXISTS interbank_rates_pkey;
ALTER TABLE IF EXISTS ONLY gold.interbank_rates DROP CONSTRAINT IF EXISTS interbank_rates_date_currency_tenor_key;
ALTER TABLE IF EXISTS ONLY gold.institutional_holdings DROP CONSTRAINT IF EXISTS institutional_holdings_ticker_holder_name_report_date_key;
ALTER TABLE IF EXISTS ONLY gold.institutional_holdings DROP CONSTRAINT IF EXISTS institutional_holdings_pkey;
ALTER TABLE IF EXISTS ONLY gold.index_metrics DROP CONSTRAINT IF EXISTS index_metrics_pkey;
ALTER TABLE IF EXISTS ONLY gold.ibkr_positions_live DROP CONSTRAINT IF EXISTS ibkr_positions_live_pkey;
ALTER TABLE IF EXISTS ONLY gold.ibkr_positions_live DROP CONSTRAINT IF EXISTS ibkr_positions_live_account_ticker_key;
ALTER TABLE IF EXISTS ONLY gold.ibkr_orders DROP CONSTRAINT IF EXISTS ibkr_orders_pkey;
ALTER TABLE IF EXISTS ONLY gold.ibkr_account_summary DROP CONSTRAINT IF EXISTS ibkr_account_summary_pkey;
ALTER TABLE IF EXISTS ONLY gold.ib_orders DROP CONSTRAINT IF EXISTS ib_orders_pkey;
ALTER TABLE IF EXISTS ONLY gold.hmm_regime_states DROP CONSTRAINT IF EXISTS hmm_regime_states_pkey;
ALTER TABLE IF EXISTS ONLY gold.hk_ipo_performance DROP CONSTRAINT IF EXISTS hk_ipo_performance_pkey;
ALTER TABLE IF EXISTS ONLY gold.hk_ipo_details DROP CONSTRAINT IF EXISTS hk_ipo_details_pkey;
ALTER TABLE IF EXISTS ONLY gold.hk_ipo_calendar DROP CONSTRAINT IF EXISTS hk_ipo_calendar_pkey;
ALTER TABLE IF EXISTS ONLY gold.hft_metrics DROP CONSTRAINT IF EXISTS hft_metrics_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.hft_metrics DROP CONSTRAINT IF EXISTS hft_metrics_pkey;
ALTER TABLE IF EXISTS ONLY gold.fx_metrics DROP CONSTRAINT IF EXISTS fx_metrics_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.fx_metrics DROP CONSTRAINT IF EXISTS fx_metrics_pkey;
ALTER TABLE IF EXISTS ONLY gold.fx_bars_5s DROP CONSTRAINT IF EXISTS fx_bars_5s_timestamp_ticker_key;
ALTER TABLE IF EXISTS ONLY gold.fx_bars_5s DROP CONSTRAINT IF EXISTS fx_bars_5s_pkey;
ALTER TABLE IF EXISTS ONLY gold.fx_alerts DROP CONSTRAINT IF EXISTS fx_alerts_pkey;
ALTER TABLE IF EXISTS ONLY gold.etf_daily_data DROP CONSTRAINT IF EXISTS etf_daily_data_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.etf_daily_data DROP CONSTRAINT IF EXISTS etf_daily_data_pkey;
ALTER TABLE IF EXISTS ONLY gold.kpis_metrics DROP CONSTRAINT IF EXISTS equities_kpis_pkey;
ALTER TABLE IF EXISTS ONLY gold.earnings_signals DROP CONSTRAINT IF EXISTS earnings_signals_symbol_earnings_date_key;
ALTER TABLE IF EXISTS ONLY gold.earnings_signals DROP CONSTRAINT IF EXISTS earnings_signals_pkey;
ALTER TABLE IF EXISTS ONLY gold.earnings_data DROP CONSTRAINT IF EXISTS earnings_data_ticker_report_date_key;
ALTER TABLE IF EXISTS ONLY gold.earnings_data DROP CONSTRAINT IF EXISTS earnings_data_pkey;
ALTER TABLE IF EXISTS ONLY gold.delisted_tickers DROP CONSTRAINT IF EXISTS delisted_tickers_ticker_delisted_date_key;
ALTER TABLE IF EXISTS ONLY gold.delisted_tickers DROP CONSTRAINT IF EXISTS delisted_tickers_pkey;
ALTER TABLE IF EXISTS ONLY gold.daily_ohlcv DROP CONSTRAINT IF EXISTS daily_ohlcv_pkey;
ALTER TABLE IF EXISTS ONLY gold.crypto_technical_metrics DROP CONSTRAINT IF EXISTS crypto_technical_metrics_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.crypto_technical_metrics DROP CONSTRAINT IF EXISTS crypto_technical_metrics_pkey;
ALTER TABLE IF EXISTS ONLY gold.crypto_metrics DROP CONSTRAINT IF EXISTS crypto_metrics_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.crypto_metrics DROP CONSTRAINT IF EXISTS crypto_metrics_pkey;
ALTER TABLE IF EXISTS ONLY gold.crypto_kpis DROP CONSTRAINT IF EXISTS crypto_kpis_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.crypto_kpis DROP CONSTRAINT IF EXISTS crypto_kpis_pkey;
ALTER TABLE IF EXISTS ONLY gold.crypto_funding_metrics DROP CONSTRAINT IF EXISTS crypto_funding_metrics_pkey;
ALTER TABLE IF EXISTS ONLY gold.cot_sentiment DROP CONSTRAINT IF EXISTS cot_sentiment_pkey;
ALTER TABLE IF EXISTS ONLY gold.consensus_ratings DROP CONSTRAINT IF EXISTS consensus_ratings_ticker_report_date_key;
ALTER TABLE IF EXISTS ONLY gold.consensus_ratings DROP CONSTRAINT IF EXISTS consensus_ratings_pkey;
ALTER TABLE IF EXISTS ONLY gold.commodity_seasonality DROP CONSTRAINT IF EXISTS commodity_seasonality_ticker_month_key;
ALTER TABLE IF EXISTS ONLY gold.commodity_seasonality DROP CONSTRAINT IF EXISTS commodity_seasonality_pkey;
ALTER TABLE IF EXISTS ONLY gold.commodity_metrics DROP CONSTRAINT IF EXISTS commodity_metrics_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.commodity_metrics DROP CONSTRAINT IF EXISTS commodity_metrics_pkey;
ALTER TABLE IF EXISTS ONLY gold.commodity_futures DROP CONSTRAINT IF EXISTS commodity_futures_ticker_date_key;
ALTER TABLE IF EXISTS ONLY gold.commodity_futures DROP CONSTRAINT IF EXISTS commodity_futures_pkey;
ALTER TABLE IF EXISTS ONLY gold.audit_events DROP CONSTRAINT IF EXISTS audit_events_pkey;
ALTER TABLE IF EXISTS ONLY gold.asset_registry DROP CONSTRAINT IF EXISTS asset_registry_pkey;
ALTER TABLE IF EXISTS ONLY gold.agent_events DROP CONSTRAINT IF EXISTS agent_events_pkey;
ALTER TABLE IF EXISTS ONLY gold.accruals_quality DROP CONSTRAINT IF EXISTS accruals_quality_ticker_quarter_key;
ALTER TABLE IF EXISTS ONLY gold.accruals_quality DROP CONSTRAINT IF EXISTS accruals_quality_pkey;
ALTER TABLE IF EXISTS ONLY consumption.vix_dashboard DROP CONSTRAINT IF EXISTS vix_dashboard_pkey;
ALTER TABLE IF EXISTS ONLY consumption.ticker_scores DROP CONSTRAINT IF EXISTS ticker_scores_pkey;
ALTER TABLE IF EXISTS ONLY consumption.strategy_scores_dynamic DROP CONSTRAINT IF EXISTS strategy_scores_dynamic_pkey;
ALTER TABLE IF EXISTS ONLY consumption.strategies_backtest_results DROP CONSTRAINT IF EXISTS strategies_backtest_results_pkey;
ALTER TABLE IF EXISTS ONLY consumption.signal_logs DROP CONSTRAINT IF EXISTS signal_logs_pkey;
ALTER TABLE IF EXISTS ONLY consumption.settings_data_sources DROP CONSTRAINT IF EXISTS settings_data_sources_pkey;
ALTER TABLE IF EXISTS ONLY consumption.settings_data_sources DROP CONSTRAINT IF EXISTS settings_data_sources_data_type_source_priority_key;
ALTER TABLE IF EXISTS ONLY consumption.research_sue_scores DROP CONSTRAINT IF EXISTS research_sue_scores_ticker_report_date_key;
ALTER TABLE IF EXISTS ONLY consumption.research_sue_scores DROP CONSTRAINT IF EXISTS research_sue_scores_pkey;
ALTER TABLE IF EXISTS ONLY consumption.research_seasonality_patterns DROP CONSTRAINT IF EXISTS research_seasonality_patterns_ticker_key;
ALTER TABLE IF EXISTS ONLY consumption.research_seasonality_patterns DROP CONSTRAINT IF EXISTS research_seasonality_patterns_pkey;
ALTER TABLE IF EXISTS ONLY consumption.research_pipeline DROP CONSTRAINT IF EXISTS research_pipeline_pkey;
ALTER TABLE IF EXISTS ONLY consumption.research_pipeline DROP CONSTRAINT IF EXISTS research_pipeline_experiment_id_key;
ALTER TABLE IF EXISTS ONLY consumption.research_contrarian_signals DROP CONSTRAINT IF EXISTS research_contrarian_signals_ticker_signal_type_key;
ALTER TABLE IF EXISTS ONLY consumption.research_contrarian_signals DROP CONSTRAINT IF EXISTS research_contrarian_signals_pkey;
ALTER TABLE IF EXISTS ONLY consumption.promoted_strategies DROP CONSTRAINT IF EXISTS promoted_strategies_strategy_id_key;
ALTER TABLE IF EXISTS ONLY consumption.promoted_strategies DROP CONSTRAINT IF EXISTS promoted_strategies_pkey;
ALTER TABLE IF EXISTS ONLY consumption.portfolio_risk_metrics DROP CONSTRAINT IF EXISTS portfolio_risk_metrics_portfolio_type_key;
ALTER TABLE IF EXISTS ONLY consumption.portfolio_risk_metrics DROP CONSTRAINT IF EXISTS portfolio_risk_metrics_pkey;
ALTER TABLE IF EXISTS ONLY consumption.portfolio_positions_current DROP CONSTRAINT IF EXISTS portfolio_positions_current_ticker_key;
ALTER TABLE IF EXISTS ONLY consumption.portfolio_positions_current DROP CONSTRAINT IF EXISTS portfolio_positions_current_pkey;
ALTER TABLE IF EXISTS ONLY consumption.performance_strategy_attribution DROP CONSTRAINT IF EXISTS performance_strategy_attribution_strategy_id_portfolio_type_key;
ALTER TABLE IF EXISTS ONLY consumption.performance_strategy_attribution DROP CONSTRAINT IF EXISTS performance_strategy_attribution_pkey;
ALTER TABLE IF EXISTS ONLY consumption.performance_monthly_returns DROP CONSTRAINT IF EXISTS performance_monthly_returns_portfolio_type_year_month_key;
ALTER TABLE IF EXISTS ONLY consumption.performance_monthly_returns DROP CONSTRAINT IF EXISTS performance_monthly_returns_pkey;
ALTER TABLE IF EXISTS ONLY consumption.markets_stocks_overview DROP CONSTRAINT IF EXISTS markets_stocks_overview_ticker_key;
ALTER TABLE IF EXISTS ONLY consumption.markets_stocks_overview DROP CONSTRAINT IF EXISTS markets_stocks_overview_pkey;
ALTER TABLE IF EXISTS ONLY consumption.markets_commodities_overview DROP CONSTRAINT IF EXISTS markets_commodities_overview_ticker_key;
ALTER TABLE IF EXISTS ONLY consumption.markets_commodities_overview DROP CONSTRAINT IF EXISTS markets_commodities_overview_pkey;
ALTER TABLE IF EXISTS ONLY consumption.market_data_snapshot DROP CONSTRAINT IF EXISTS market_data_snapshot_pkey;
ALTER TABLE IF EXISTS ONLY consumption.macro_calendar_dashboard DROP CONSTRAINT IF EXISTS macro_calendar_dashboard_pkey;
ALTER TABLE IF EXISTS ONLY consumption.hft_matrix DROP CONSTRAINT IF EXISTS hft_matrix_ticker_timestamp_key;
ALTER TABLE IF EXISTS ONLY consumption.hft_matrix DROP CONSTRAINT IF EXISTS hft_matrix_pkey;
ALTER TABLE IF EXISTS ONLY consumption.global_state DROP CONSTRAINT IF EXISTS global_state_pkey;
ALTER TABLE IF EXISTS ONLY consumption.global_state DROP CONSTRAINT IF EXISTS global_state_key_key;
ALTER TABLE IF EXISTS ONLY consumption.dashboard_summary_cards DROP CONSTRAINT IF EXISTS dashboard_summary_cards_pkey;
ALTER TABLE IF EXISTS ONLY consumption.dashboard_summary_cards DROP CONSTRAINT IF EXISTS dashboard_summary_cards_card_key_key;
ALTER TABLE IF EXISTS ONLY consumption.dashboard_opportunities_top DROP CONSTRAINT IF EXISTS dashboard_opportunities_top_ticker_signal_type_key;
ALTER TABLE IF EXISTS ONLY consumption.dashboard_opportunities_top DROP CONSTRAINT IF EXISTS dashboard_opportunities_top_pkey;
ALTER TABLE IF EXISTS ONLY consumption.dashboard_market_overview DROP CONSTRAINT IF EXISTS dashboard_market_overview_region_index_ticker_key;
ALTER TABLE IF EXISTS ONLY consumption.dashboard_market_overview DROP CONSTRAINT IF EXISTS dashboard_market_overview_pkey;
ALTER TABLE IF EXISTS ONLY consumption.crypto_funding_snapshot DROP CONSTRAINT IF EXISTS crypto_funding_snapshot_pkey;
ALTER TABLE IF EXISTS ONLY consumption.cot_snapshot DROP CONSTRAINT IF EXISTS cot_snapshot_pkey;
ALTER TABLE IF EXISTS ONLY consumption.commodities DROP CONSTRAINT IF EXISTS commodities_pkey;
ALTER TABLE IF EXISTS ONLY consumption.agent_health DROP CONSTRAINT IF EXISTS agent_health_pkey;
ALTER TABLE IF EXISTS ONLY consumption.agent_health DROP CONSTRAINT IF EXISTS agent_health_agent_id_key;
ALTER TABLE IF EXISTS ONLY bronze.yf_prices DROP CONSTRAINT IF EXISTS yf_prices_ticker_date_key;
ALTER TABLE IF EXISTS ONLY bronze.yf_prices DROP CONSTRAINT IF EXISTS yf_prices_pkey;
ALTER TABLE IF EXISTS ONLY bronze.yf_commodity_futures DROP CONSTRAINT IF EXISTS yf_commodity_futures_ticker_date_key;
ALTER TABLE IF EXISTS ONLY bronze.yf_commodity_futures DROP CONSTRAINT IF EXISTS yf_commodity_futures_pkey;
ALTER TABLE IF EXISTS ONLY bronze.raw_stock_data DROP CONSTRAINT IF EXISTS raw_stock_data_pkey;
ALTER TABLE IF EXISTS ONLY bronze.raw_news DROP CONSTRAINT IF EXISTS raw_news_pkey;
ALTER TABLE IF EXISTS ONLY bronze.nfp_consensus_proxy DROP CONSTRAINT IF EXISTS nfp_consensus_proxy_pkey;
ALTER TABLE IF EXISTS ONLY bronze.manual_earnings DROP CONSTRAINT IF EXISTS manual_earnings_ticker_report_date_key;
ALTER TABLE IF EXISTS ONLY bronze.manual_earnings DROP CONSTRAINT IF EXISTS manual_earnings_pkey;
ALTER TABLE IF EXISTS ONLY bronze.institutional_holdings DROP CONSTRAINT IF EXISTS institutional_holdings_ticker_report_date_key;
ALTER TABLE IF EXISTS ONLY bronze.institutional_holdings DROP CONSTRAINT IF EXISTS institutional_holdings_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_positions DROP CONSTRAINT IF EXISTS ibkr_positions_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_positions_live DROP CONSTRAINT IF EXISTS ibkr_positions_live_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_positions_live DROP CONSTRAINT IF EXISTS ibkr_positions_live_account_ticker_key;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_positions DROP CONSTRAINT IF EXISTS ibkr_positions_account_con_id_recorded_at_key;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_orders DROP CONSTRAINT IF EXISTS ibkr_orders_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_orders DROP CONSTRAINT IF EXISTS ibkr_orders_account_order_id_perm_id_key;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_historical_bars DROP CONSTRAINT IF EXISTS ibkr_historical_bars_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_historical_bars DROP CONSTRAINT IF EXISTS ibkr_historical_bars_con_id_bar_time_bar_size_what_to_show_key;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_fx_ticks DROP CONSTRAINT IF EXISTS ibkr_fx_ticks_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_fx_ticks DROP CONSTRAINT IF EXISTS ibkr_fx_ticks_pair_timestamp_key;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_fx_bars DROP CONSTRAINT IF EXISTS ibkr_fx_bars_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_fx_bars DROP CONSTRAINT IF EXISTS ibkr_fx_bars_pair_bar_size_timestamp_key;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_contracts DROP CONSTRAINT IF EXISTS ibkr_contracts_pkey;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_contracts DROP CONSTRAINT IF EXISTS ibkr_contracts_con_id_key;
ALTER TABLE IF EXISTS ONLY bronze.ibkr_account_summary DROP CONSTRAINT IF EXISTS ibkr_account_summary_pkey;
ALTER TABLE IF EXISTS ONLY bronze.hkex_ipo_calendar_raw DROP CONSTRAINT IF EXISTS hkex_ipo_calendar_raw_ticker_listing_date_key;
ALTER TABLE IF EXISTS ONLY bronze.hkex_ipo_calendar_raw DROP CONSTRAINT IF EXISTS hkex_ipo_calendar_raw_pkey;
ALTER TABLE IF EXISTS ONLY bronze.fx_prices DROP CONSTRAINT IF EXISTS fx_prices_pkey;
ALTER TABLE IF EXISTS ONLY bronze.fx_prices DROP CONSTRAINT IF EXISTS fx_prices_pair_timestamp_key;
ALTER TABLE IF EXISTS ONLY bronze.fred_macro_indicators DROP CONSTRAINT IF EXISTS fred_macro_indicators_pkey;
ALTER TABLE IF EXISTS ONLY bronze.fmp_institutional_holdings DROP CONSTRAINT IF EXISTS fmp_institutional_holdings_ticker_holder_name_report_date_key;
ALTER TABLE IF EXISTS ONLY bronze.fmp_institutional_holdings DROP CONSTRAINT IF EXISTS fmp_institutional_holdings_pkey;
ALTER TABLE IF EXISTS ONLY bronze.earnings_calendar DROP CONSTRAINT IF EXISTS earnings_calendar_ticker_earnings_date_key;
ALTER TABLE IF EXISTS ONLY bronze.earnings_calendar DROP CONSTRAINT IF EXISTS earnings_calendar_pkey;
ALTER TABLE IF EXISTS ONLY bronze.data_quality_log DROP CONSTRAINT IF EXISTS data_quality_log_source_table_ticker_record_date_issue_type_key;
ALTER TABLE IF EXISTS ONLY bronze.data_quality_log DROP CONSTRAINT IF EXISTS data_quality_log_pkey;
ALTER TABLE IF EXISTS ONLY bronze.binance_funding_rates DROP CONSTRAINT IF EXISTS binance_funding_rates_ticker_funding_time_key;
ALTER TABLE IF EXISTS ONLY bronze.binance_funding_rates DROP CONSTRAINT IF EXISTS binance_funding_rates_pkey;
ALTER TABLE IF EXISTS ONLY bronze.binance_crypto_ohlcv DROP CONSTRAINT IF EXISTS binance_crypto_ohlcv_ticker_interval_timestamp_key;
ALTER TABLE IF EXISTS ONLY bronze.binance_crypto_ohlcv DROP CONSTRAINT IF EXISTS binance_crypto_ohlcv_pkey;
ALTER TABLE IF EXISTS silver.unified_prices ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.unified_ipo_calendar ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.unified_earnings ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.technical_indicators ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.quarantine ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.market_indices ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.historical_stock_data ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.historical_news ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.earnings_calendar ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.crypto_ohlcv_normalized ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS silver.asset_registry ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS shared.agent_tasks ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS research_sandbox.research_log ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS research_sandbox.daily_strategy_ideas ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS research_sandbox.daily_market_rca ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.trade_executions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.system_config ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.sync_schedules ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.sue_scores ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_universes ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_ticker_scores ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_thresholds ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_templates ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_signal_criteria ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_performance_log ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_definitions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.strategy_configs ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.signal_cancellations ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.sentiment_mart ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.sector_etfs ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.seasonality_patterns ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.s9_paper_trades ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.s9_macd_signals ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.positions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.portfolio_snapshots ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.paper_trades ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.paper_strategies ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.paper_run_log ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.nfp_equity_drift_backtests ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.metric_definitions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.market_sentiment_daily ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.market_regimes ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.macro_indicators ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.llm_key_entities_config ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.interbank_rates ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.institutional_holdings ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.ibkr_positions_live ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.ibkr_orders ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.ib_orders ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.hft_metrics ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.fx_metrics ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.fx_bars_5s ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.fx_alerts ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.etf_daily_data ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.earnings_signals ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.earnings_data ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.delisted_tickers ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.crypto_technical_metrics ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.crypto_metrics ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.crypto_kpis ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.consensus_ratings ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.commodity_seasonality ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.commodity_metrics ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.commodity_futures ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.audit_events ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS gold.accruals_quality ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.strategies_backtest_results ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.signal_logs ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.settings_data_sources ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.research_sue_scores ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.research_seasonality_patterns ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.research_pipeline ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.research_contrarian_signals ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.promoted_strategies ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.portfolio_risk_metrics ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.portfolio_positions_current ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.performance_strategy_attribution ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.performance_monthly_returns ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.markets_stocks_overview ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.markets_commodities_overview ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.hft_matrix ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.global_state ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.dashboard_summary_cards ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.dashboard_opportunities_top ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.dashboard_market_overview ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.commodities ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS consumption.agent_health ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.yf_prices ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.yf_commodity_futures ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.raw_stock_data ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.raw_news ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.manual_earnings ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.institutional_holdings ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.ibkr_positions_live ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.ibkr_positions ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.ibkr_orders ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.ibkr_historical_bars ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.ibkr_fx_ticks ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.ibkr_fx_bars ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.ibkr_contracts ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.hkex_ipo_calendar_raw ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.fx_prices ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.fmp_institutional_holdings ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.earnings_calendar ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.data_quality_log ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.binance_funding_rates ALTER COLUMN id DROP DEFAULT;
ALTER TABLE IF EXISTS bronze.binance_crypto_ohlcv ALTER COLUMN id DROP DEFAULT;
DROP TABLE IF EXISTS silver.vix_indicators;
DROP SEQUENCE IF EXISTS silver.unified_prices_new_id_seq;
DROP TABLE IF EXISTS silver.unified_ipo_performance;
DROP SEQUENCE IF EXISTS silver.unified_ipo_calendar_id_seq;
DROP TABLE IF EXISTS silver.unified_ipo_calendar;
DROP SEQUENCE IF EXISTS silver.unified_earnings_id_seq;
DROP SEQUENCE IF EXISTS silver.technical_indicators_id_seq;
DROP TABLE IF EXISTS silver.technical_indicators;
DROP SEQUENCE IF EXISTS silver.quarantine_id_seq;
DROP TABLE IF EXISTS silver.quarantine;
DROP SEQUENCE IF EXISTS silver.market_indices_id_seq;
DROP TABLE IF EXISTS silver.market_indices;
DROP TABLE IF EXISTS silver.macro_event_calendar;
DROP SEQUENCE IF EXISTS silver.historical_stock_data_id_seq;
DROP TABLE IF EXISTS silver.historical_stock_data;
DROP SEQUENCE IF EXISTS silver.historical_news_id_seq;
DROP TABLE IF EXISTS silver.historical_news;
DROP TABLE IF EXISTS silver.funding_rates_daily;
DROP SEQUENCE IF EXISTS silver.earnings_calendar_id_seq;
DROP TABLE IF EXISTS silver.earnings_calendar;
DROP SEQUENCE IF EXISTS silver.crypto_ohlcv_normalized_id_seq;
DROP TABLE IF EXISTS silver.crypto_ohlcv_normalized;
DROP TABLE IF EXISTS silver.cot_euro_fx_daily;
DROP SEQUENCE IF EXISTS silver.asset_registry_id_seq;
DROP TABLE IF EXISTS silver.asset_registry;
DROP VIEW IF EXISTS shared.v_pending_tasks;
DROP SEQUENCE IF EXISTS shared.agent_tasks_id_seq;
DROP TABLE IF EXISTS shared.agent_tasks;
DROP TABLE IF EXISTS research_sandbox.vix_data;
DROP TABLE IF EXISTS research_sandbox.ticker_sectors;
DROP TABLE IF EXISTS research_sandbox.strategy_universe;
DROP TABLE IF EXISTS research_sandbox.spy_ohlcv;
DROP SEQUENCE IF EXISTS research_sandbox.research_log_id_seq;
DROP TABLE IF EXISTS research_sandbox.research_log;
DROP TABLE IF EXISTS research_sandbox.ohlcv_backtest;
DROP SEQUENCE IF EXISTS research_sandbox.daily_strategy_ideas_id_seq;
DROP TABLE IF EXISTS research_sandbox.daily_strategy_ideas;
DROP SEQUENCE IF EXISTS research_sandbox.daily_market_rca_id_seq;
DROP TABLE IF EXISTS research_sandbox.daily_market_rca;
DROP TABLE IF EXISTS research_sandbox.benchmark_indices;
DROP TABLE IF EXISTS openclaw_researcher.gold_layer_state;
DROP VIEW IF EXISTS gold.v_upcoming_events;
DROP VIEW IF EXISTS gold.v_strategy_book_extended;
DROP VIEW IF EXISTS gold.v_strategy_book;
DROP VIEW IF EXISTS gold.v_seasonal_opportunities;
DROP VIEW IF EXISTS gold.v_s015_macro_enriched;
DROP VIEW IF EXISTS gold.v_paper_trade_summary;
DROP VIEW IF EXISTS gold.v_paper_trade_history;
DROP VIEW IF EXISTS gold.v_paper_system_status;
DROP VIEW IF EXISTS gold.v_paper_open_positions;
DROP VIEW IF EXISTS gold.v_paper_daily_runs;
DROP VIEW IF EXISTS gold.v_latest_sue_scores;
DROP VIEW IF EXISTS gold.v_etl_pipeline_health;
DROP TABLE IF EXISTS gold.vix_regime;
DROP VIEW IF EXISTS gold.v_signal_proximity;
DROP TABLE IF EXISTS silver.unified_earnings;
DROP VIEW IF EXISTS gold.v_earnings_coverage;
DROP VIEW IF EXISTS gold.v_commodities_coverage;
DROP VIEW IF EXISTS gold.v_agent_workflows;
DROP VIEW IF EXISTS gold.v_agent_pending_work;
DROP VIEW IF EXISTS gold.v_agent_gold_layer_status;
DROP VIEW IF EXISTS gold.v_agent_completed_work;
DROP VIEW IF EXISTS gold.v_agent_activity_feed;
DROP SEQUENCE IF EXISTS gold.trade_executions_id_seq;
DROP TABLE IF EXISTS gold.trade_executions;
DROP SEQUENCE IF EXISTS gold.system_config_id_seq;
DROP TABLE IF EXISTS gold.system_config;
DROP SEQUENCE IF EXISTS gold.sync_schedules_id_seq;
DROP TABLE IF EXISTS gold.sync_schedules;
DROP SEQUENCE IF EXISTS gold.sue_scores_id_seq;
DROP TABLE IF EXISTS gold.sue_scores;
DROP SEQUENCE IF EXISTS gold.strategy_universes_id_seq;
DROP TABLE IF EXISTS gold.strategy_universes;
DROP SEQUENCE IF EXISTS gold.strategy_ticker_scores_id_seq;
DROP TABLE IF EXISTS gold.strategy_ticker_scores;
DROP SEQUENCE IF EXISTS gold.strategy_thresholds_id_seq;
DROP TABLE IF EXISTS gold.strategy_thresholds;
DROP SEQUENCE IF EXISTS gold.strategy_templates_id_seq;
DROP TABLE IF EXISTS gold.strategy_templates;
DROP TABLE IF EXISTS gold.strategy_signals;
DROP SEQUENCE IF EXISTS gold.strategy_signal_criteria_id_seq;
DROP TABLE IF EXISTS gold.strategy_signal_criteria;
DROP TABLE IF EXISTS gold.strategy_risk_reviews;
DROP TABLE IF EXISTS gold.strategy_research;
DROP TABLE IF EXISTS gold.strategy_registry;
DROP TABLE IF EXISTS gold.strategy_qa_reviews;
DROP SEQUENCE IF EXISTS gold.strategy_performance_log_id_seq;
DROP TABLE IF EXISTS gold.strategy_performance_log;
DROP SEQUENCE IF EXISTS gold.strategy_definitions_id_seq;
DROP TABLE IF EXISTS gold.strategy_definitions;
DROP SEQUENCE IF EXISTS gold.strategy_configs_id_seq;
DROP TABLE IF EXISTS gold.strategy_configs;
DROP TABLE IF EXISTS gold.strategy_backtests;
DROP TABLE IF EXISTS gold.strategy_backtest_trades;
DROP TABLE IF EXISTS gold.strategy_backtest_runs;
DROP TABLE IF EXISTS gold.stock_metrics_new;
DROP VIEW IF EXISTS gold.stock_metrics;
DROP TABLE IF EXISTS gold.stock_metrics_history;
DROP SEQUENCE IF EXISTS gold.signal_cancellations_id_seq;
DROP TABLE IF EXISTS gold.signal_cancellations;
DROP SEQUENCE IF EXISTS gold.sentiment_mart_id_seq;
DROP TABLE IF EXISTS gold.sentiment_mart;
DROP SEQUENCE IF EXISTS gold.sector_etfs_id_seq;
DROP SEQUENCE IF EXISTS gold.seasonality_patterns_id_seq;
DROP TABLE IF EXISTS gold.seasonality_patterns;
DROP SEQUENCE IF EXISTS gold.s9_paper_trades_id_seq;
DROP TABLE IF EXISTS gold.s9_paper_trades;
DROP SEQUENCE IF EXISTS gold.s9_macd_signals_id_seq;
DROP TABLE IF EXISTS gold.s9_macd_signals;
DROP TABLE IF EXISTS gold.regime_label;
DROP TABLE IF EXISTS gold.regime_features;
DROP SEQUENCE IF EXISTS gold.positions_id_seq;
DROP TABLE IF EXISTS gold.positions;
DROP SEQUENCE IF EXISTS gold.portfolio_snapshots_id_seq;
DROP TABLE IF EXISTS gold.portfolio_snapshots;
DROP TABLE IF EXISTS gold.platform_settings;
DROP SEQUENCE IF EXISTS gold.paper_trades_id_seq;
DROP TABLE IF EXISTS gold.paper_trades;
DROP SEQUENCE IF EXISTS gold.paper_strategies_id_seq;
DROP TABLE IF EXISTS gold.paper_strategies;
DROP SEQUENCE IF EXISTS gold.paper_run_log_id_seq;
DROP TABLE IF EXISTS gold.paper_run_log;
DROP SEQUENCE IF EXISTS gold.nfp_equity_drift_backtests_id_seq;
DROP TABLE IF EXISTS gold.nfp_equity_drift_backtests;
DROP SEQUENCE IF EXISTS gold.metric_definitions_id_seq;
DROP TABLE IF EXISTS gold.metric_definitions;
DROP SEQUENCE IF EXISTS gold.market_sentiment_daily_id_seq;
DROP TABLE IF EXISTS gold.market_sentiment_daily;
DROP SEQUENCE IF EXISTS gold.market_regimes_id_seq;
DROP TABLE IF EXISTS gold.market_regimes;
DROP SEQUENCE IF EXISTS gold.macro_indicators_id_seq;
DROP TABLE IF EXISTS gold.macro_event_flags;
DROP TABLE IF EXISTS gold.kpis_metrics;
DROP SEQUENCE IF EXISTS gold.key_entities_config_id_seq;
DROP TABLE IF EXISTS gold.llm_key_entities_config;
DROP SEQUENCE IF EXISTS gold.interbank_rates_id_seq;
DROP SEQUENCE IF EXISTS gold.institutional_holdings_id_seq;
DROP TABLE IF EXISTS gold.institutional_holdings;
DROP SEQUENCE IF EXISTS gold.ibkr_positions_live_id_seq;
DROP TABLE IF EXISTS gold.ibkr_positions_live;
DROP SEQUENCE IF EXISTS gold.ibkr_orders_id_seq;
DROP TABLE IF EXISTS gold.ibkr_orders;
DROP TABLE IF EXISTS gold.ibkr_account_summary;
DROP SEQUENCE IF EXISTS gold.ib_orders_id_seq;
DROP TABLE IF EXISTS gold.ib_orders;
DROP TABLE IF EXISTS gold.hmm_regime_states;
DROP SEQUENCE IF EXISTS gold.hft_metrics_id_seq;
DROP TABLE IF EXISTS gold.hft_metrics;
DROP SEQUENCE IF EXISTS gold.fx_metrics_id_seq;
DROP SEQUENCE IF EXISTS gold.fx_bars_5s_id_seq;
DROP TABLE IF EXISTS gold.fx_bars_5s;
DROP SEQUENCE IF EXISTS gold.fx_alerts_id_seq;
DROP TABLE IF EXISTS gold.fx_alerts;
DROP SEQUENCE IF EXISTS gold.etf_daily_data_id_seq;
DROP TABLE IF EXISTS gold.etf_daily_data;
DROP SEQUENCE IF EXISTS gold.earnings_signals_id_seq;
DROP SEQUENCE IF EXISTS gold.earnings_data_id_seq;
DROP SEQUENCE IF EXISTS gold.delisted_tickers_id_seq;
DROP TABLE IF EXISTS gold.delisted_tickers;
DROP TABLE IF EXISTS gold.daily_ohlcv;
DROP SEQUENCE IF EXISTS gold.crypto_technical_metrics_id_seq;
DROP TABLE IF EXISTS gold.crypto_technical_metrics;
DROP SEQUENCE IF EXISTS gold.crypto_metrics_id_seq;
DROP SEQUENCE IF EXISTS gold.crypto_kpis_id_seq;
DROP TABLE IF EXISTS gold.crypto_kpis;
DROP TABLE IF EXISTS gold.crypto_funding_metrics;
DROP TABLE IF EXISTS gold.cot_sentiment;
DROP SEQUENCE IF EXISTS gold.consensus_ratings_id_seq;
DROP TABLE IF EXISTS gold.consensus_ratings;
DROP SEQUENCE IF EXISTS gold.commodity_seasonality_id_seq;
DROP TABLE IF EXISTS gold.commodity_seasonality;
DROP SEQUENCE IF EXISTS gold.commodity_metrics_id_seq;
DROP SEQUENCE IF EXISTS gold.commodity_futures_id_seq;
DROP SEQUENCE IF EXISTS gold.audit_events_id_seq;
DROP TABLE IF EXISTS gold.audit_events;
DROP TABLE IF EXISTS gold.asset_registry;
DROP TABLE IF EXISTS gold.agent_events;
DROP SEQUENCE IF EXISTS gold.accruals_quality_id_seq;
DROP TABLE IF EXISTS gold.accruals_quality;
DROP TABLE IF EXISTS consumption.vix_dashboard;
DROP VIEW IF EXISTS consumption.v_s101_hibor_input;
DROP VIEW IF EXISTS consumption.v_s015_sector_rotation;
DROP VIEW IF EXISTS gold.v_s015_sector_rotation;
DROP TABLE IF EXISTS gold.sector_etfs;
DROP TABLE IF EXISTS gold.macro_indicators;
DROP TABLE IF EXISTS gold.commodity_futures;
DROP VIEW IF EXISTS consumption.v_s014_earnings_signals;
DROP VIEW IF EXISTS gold.v_s014_earnings_signals;
DROP TABLE IF EXISTS silver.unified_prices;
DROP TABLE IF EXISTS gold.earnings_data;
DROP VIEW IF EXISTS consumption.v_research_suescores;
DROP VIEW IF EXISTS consumption.v_research_seasonality;
DROP VIEW IF EXISTS consumption.v_research_contrarian;
DROP VIEW IF EXISTS consumption.v_portfolio_risk;
DROP VIEW IF EXISTS consumption.v_performance_monthlyreturns;
DROP VIEW IF EXISTS consumption.v_performance_attribution;
DROP VIEW IF EXISTS consumption.v_markets_stocks;
DROP VIEW IF EXISTS consumption.v_markets_commodities;
DROP VIEW IF EXISTS consumption.v_hibor_1m;
DROP TABLE IF EXISTS gold.interbank_rates;
DROP VIEW IF EXISTS consumption.v_earnings_signals;
DROP TABLE IF EXISTS gold.earnings_signals;
DROP VIEW IF EXISTS consumption.v_earnings_history;
DROP VIEW IF EXISTS silver.v_earnings_clean;
DROP VIEW IF EXISTS consumption.v_earnings_clean;
DROP VIEW IF EXISTS consumption.v_dashboard_marketoverview;
DROP VIEW IF EXISTS consumption.v_dashboard_kpis;
DROP VIEW IF EXISTS consumption.v_commodity_metrics;
DROP VIEW IF EXISTS gold.v_commodity_daily;
DROP TABLE IF EXISTS gold.commodity_metrics;
DROP TABLE IF EXISTS consumption.ticker_scores;
DROP TABLE IF EXISTS consumption.strategy_scores_dynamic;
DROP SEQUENCE IF EXISTS consumption.strategies_backtest_results_id_seq;
DROP TABLE IF EXISTS consumption.strategies_backtest_results;
DROP VIEW IF EXISTS consumption.stock;
DROP SEQUENCE IF EXISTS consumption.signal_logs_id_seq;
DROP TABLE IF EXISTS consumption.signal_logs;
DROP SEQUENCE IF EXISTS consumption.settings_data_sources_id_seq;
DROP TABLE IF EXISTS consumption.settings_data_sources;
DROP SEQUENCE IF EXISTS consumption.research_sue_scores_id_seq;
DROP TABLE IF EXISTS consumption.research_sue_scores;
DROP SEQUENCE IF EXISTS consumption.research_seasonality_patterns_id_seq;
DROP TABLE IF EXISTS consumption.research_seasonality_patterns;
DROP SEQUENCE IF EXISTS consumption.research_pipeline_id_seq;
DROP TABLE IF EXISTS consumption.research_pipeline;
DROP SEQUENCE IF EXISTS consumption.research_contrarian_signals_id_seq;
DROP TABLE IF EXISTS consumption.research_contrarian_signals;
DROP SEQUENCE IF EXISTS consumption.promoted_strategies_id_seq;
DROP TABLE IF EXISTS consumption.promoted_strategies;
DROP SEQUENCE IF EXISTS consumption.portfolio_risk_metrics_id_seq;
DROP TABLE IF EXISTS consumption.portfolio_risk_metrics;
DROP SEQUENCE IF EXISTS consumption.portfolio_positions_current_id_seq;
DROP TABLE IF EXISTS consumption.portfolio_positions_current;
DROP SEQUENCE IF EXISTS consumption.performance_strategy_attribution_id_seq;
DROP TABLE IF EXISTS consumption.performance_strategy_attribution;
DROP SEQUENCE IF EXISTS consumption.performance_monthly_returns_id_seq;
DROP TABLE IF EXISTS consumption.performance_monthly_returns;
DROP SEQUENCE IF EXISTS consumption.markets_stocks_overview_id_seq;
DROP TABLE IF EXISTS consumption.markets_stocks_overview;
DROP VIEW IF EXISTS consumption.markets_indices_overview;
DROP SEQUENCE IF EXISTS consumption.markets_commodities_overview_id_seq;
DROP TABLE IF EXISTS consumption.markets_commodities_overview;
DROP TABLE IF EXISTS consumption.market_data_snapshot;
DROP VIEW IF EXISTS consumption.market;
DROP TABLE IF EXISTS consumption.macro_calendar_dashboard;
DROP VIEW IF EXISTS consumption.index_metrics;
DROP TABLE IF EXISTS gold.index_metrics;
DROP VIEW IF EXISTS consumption.hkex_ipo_sector_performance;
DROP TABLE IF EXISTS gold.hk_ipo_performance;
DROP TABLE IF EXISTS gold.hk_ipo_details;
DROP TABLE IF EXISTS gold.hk_ipo_calendar;
DROP SEQUENCE IF EXISTS consumption.hft_matrix_id_seq;
DROP TABLE IF EXISTS consumption.hft_matrix;
DROP SEQUENCE IF EXISTS consumption.global_state_id_seq;
DROP TABLE IF EXISTS consumption.global_state;
DROP VIEW IF EXISTS consumption.fx;
DROP TABLE IF EXISTS gold.fx_metrics;
DROP SEQUENCE IF EXISTS consumption.dashboard_summary_cards_id_seq;
DROP TABLE IF EXISTS consumption.dashboard_summary_cards;
DROP SEQUENCE IF EXISTS consumption.dashboard_opportunities_top_id_seq;
DROP TABLE IF EXISTS consumption.dashboard_opportunities_top;
DROP SEQUENCE IF EXISTS consumption.dashboard_market_overview_id_seq;
DROP TABLE IF EXISTS consumption.dashboard_market_overview;
DROP TABLE IF EXISTS consumption.crypto_funding_snapshot;
DROP VIEW IF EXISTS consumption.crypto;
DROP TABLE IF EXISTS gold.crypto_metrics;
DROP TABLE IF EXISTS consumption.cot_snapshot;
DROP VIEW IF EXISTS consumption.commodity;
DROP SEQUENCE IF EXISTS consumption.commodities_id_seq;
DROP TABLE IF EXISTS consumption.commodities;
DROP SEQUENCE IF EXISTS consumption.agent_health_id_seq;
DROP TABLE IF EXISTS consumption.agent_health;
DROP SEQUENCE IF EXISTS bronze.yf_prices_id_seq;
DROP TABLE IF EXISTS bronze.yf_prices;
DROP SEQUENCE IF EXISTS bronze.yf_commodity_futures_id_seq;
DROP TABLE IF EXISTS bronze.yf_commodity_futures;
DROP SEQUENCE IF EXISTS bronze.raw_stock_data_id_seq;
DROP TABLE IF EXISTS bronze.raw_stock_data;
DROP SEQUENCE IF EXISTS bronze.raw_news_id_seq;
DROP TABLE IF EXISTS bronze.raw_news;
DROP TABLE IF EXISTS bronze.nfp_consensus_proxy;
DROP SEQUENCE IF EXISTS bronze.manual_earnings_id_seq;
DROP TABLE IF EXISTS bronze.manual_earnings;
DROP SEQUENCE IF EXISTS bronze.institutional_holdings_id_seq;
DROP TABLE IF EXISTS bronze.institutional_holdings;
DROP SEQUENCE IF EXISTS bronze.ibkr_positions_live_id_seq;
DROP TABLE IF EXISTS bronze.ibkr_positions_live;
DROP SEQUENCE IF EXISTS bronze.ibkr_positions_id_seq;
DROP TABLE IF EXISTS bronze.ibkr_positions;
DROP SEQUENCE IF EXISTS bronze.ibkr_orders_id_seq;
DROP TABLE IF EXISTS bronze.ibkr_orders;
DROP SEQUENCE IF EXISTS bronze.ibkr_historical_bars_id_seq;
DROP TABLE IF EXISTS bronze.ibkr_historical_bars;
DROP SEQUENCE IF EXISTS bronze.ibkr_fx_ticks_id_seq;
DROP TABLE IF EXISTS bronze.ibkr_fx_ticks;
DROP SEQUENCE IF EXISTS bronze.ibkr_fx_bars_id_seq;
DROP TABLE IF EXISTS bronze.ibkr_fx_bars;
DROP SEQUENCE IF EXISTS bronze.ibkr_contracts_id_seq;
DROP TABLE IF EXISTS bronze.ibkr_contracts;
DROP TABLE IF EXISTS bronze.ibkr_account_summary;
DROP SEQUENCE IF EXISTS bronze.hkex_ipo_calendar_raw_id_seq;
DROP TABLE IF EXISTS bronze.hkex_ipo_calendar_raw;
DROP SEQUENCE IF EXISTS bronze.fx_prices_id_seq;
DROP TABLE IF EXISTS bronze.fx_prices;
DROP TABLE IF EXISTS bronze.fred_macro_indicators;
DROP SEQUENCE IF EXISTS bronze.fmp_institutional_holdings_id_seq;
DROP TABLE IF EXISTS bronze.fmp_institutional_holdings;
DROP SEQUENCE IF EXISTS bronze.earnings_calendar_id_seq;
DROP TABLE IF EXISTS bronze.earnings_calendar;
DROP SEQUENCE IF EXISTS bronze.data_quality_log_id_seq;
DROP TABLE IF EXISTS bronze.data_quality_log;
DROP SEQUENCE IF EXISTS bronze.binance_funding_rates_id_seq;
DROP TABLE IF EXISTS bronze.binance_funding_rates;
DROP SEQUENCE IF EXISTS bronze.binance_crypto_ohlcv_id_seq;
DROP TABLE IF EXISTS bronze.binance_crypto_ohlcv;
DROP FUNCTION IF EXISTS silver.refresh_unified_prices();
DROP FUNCTION IF EXISTS shared.complete_task(p_task_id integer, p_response jsonb, p_error text);
DROP FUNCTION IF EXISTS shared.claim_task(p_task_id integer, p_agent character varying);
DROP FUNCTION IF EXISTS gold.set_updated_at();
DROP FUNCTION IF EXISTS gold.refresh_market_metrics();
DROP FUNCTION IF EXISTS gold.generate_inside_day_signals(p_date date);
DROP FUNCTION IF EXISTS consumption.run_hourly_refresh();
DROP FUNCTION IF EXISTS consumption.refresh_dashboard_summary();
DROP FUNCTION IF EXISTS bronze.update_last_modified();
DROP EXTENSION IF EXISTS "uuid-ossp";
DROP SCHEMA IF EXISTS silver;
DROP SCHEMA IF EXISTS shared;
DROP SCHEMA IF EXISTS research_sandbox;
DROP SCHEMA IF EXISTS reseach_sandbox;
DROP SCHEMA IF EXISTS openclaw_researcher;
DROP SCHEMA IF EXISTS gold;
DROP SCHEMA IF EXISTS consumption;
DROP SCHEMA IF EXISTS bronze;
--
-- Name: bronze; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA bronze;


--
-- Name: SCHEMA bronze; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA bronze IS 'Raw data zone - data as received from external sources';


--
-- Name: consumption; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA consumption;


--
-- Name: SCHEMA consumption; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA consumption IS 'UI consumption layer - tables directly powering the dashboard';


--
-- Name: gold; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA gold;


--
-- Name: SCHEMA gold; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA gold IS 'Curated data marts - domain-specific analytics';


--
-- Name: openclaw_researcher; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA openclaw_researcher;


--
-- Name: reseach_sandbox; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA reseach_sandbox;


--
-- Name: research_sandbox; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA research_sandbox;


--
-- Name: shared; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA shared;


--
-- Name: silver; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA silver;


--
-- Name: SCHEMA silver; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON SCHEMA silver IS 'Unified data zone - cleaned and normalized data';


--
-- Name: uuid-ossp; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA public;


--
-- Name: EXTENSION "uuid-ossp"; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION "uuid-ossp" IS 'generate universally unique identifiers (UUIDs)';


--
-- Name: update_last_modified(); Type: FUNCTION; Schema: bronze; Owner: -
--

CREATE FUNCTION bronze.update_last_modified() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.last_modified = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: refresh_dashboard_summary(); Type: FUNCTION; Schema: consumption; Owner: -
--

CREATE FUNCTION consumption.refresh_dashboard_summary() RETURNS integer
    LANGUAGE plpgsql
    AS $_$
DECLARE v_updated INTEGER := 0;
BEGIN
    INSERT INTO consumption.Dashboard_Summary_Cards (card_key, card_title, value_display, value_numeric, trend, last_updated)
    SELECT 'total_positions', 'Total Positions', COUNT(*)::TEXT, COUNT(*)::DECIMAL, 'FLAT', NOW() FROM gold.positions WHERE status = 'open'
    ON CONFLICT (card_key) DO UPDATE SET value_display = EXCLUDED.value_display, value_numeric = EXCLUDED.value_numeric, trend = EXCLUDED.trend, last_updated = NOW();
    
    INSERT INTO consumption.Dashboard_Summary_Cards (card_key, card_title, value_display, value_numeric, trend, last_updated)
    SELECT 'open_pnl', 'Open P&L', '$' || TO_CHAR(COALESCE(SUM(unrealized_pnl), 0), 'FM999,999,999.00'), COALESCE(SUM(unrealized_pnl), 0),
        CASE WHEN COALESCE(SUM(unrealized_pnl), 0) > 0 THEN 'UP' WHEN COALESCE(SUM(unrealized_pnl), 0) < 0 THEN 'DOWN' ELSE 'FLAT' END, NOW()
    FROM gold.positions WHERE status = 'open'
    ON CONFLICT (card_key) DO UPDATE SET value_display = EXCLUDED.value_display, value_numeric = EXCLUDED.value_numeric, trend = EXCLUDED.trend, last_updated = NOW();
    
    GET DIAGNOSTICS v_updated = ROW_COUNT;
    RETURN v_updated;
END;
$_$;


--
-- Name: run_hourly_refresh(); Type: FUNCTION; Schema: consumption; Owner: -
--

CREATE FUNCTION consumption.run_hourly_refresh() RETURNS TABLE(layer text, records_processed integer)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY SELECT 'silver.unified_prices'::TEXT, silver.refresh_unified_prices();
    RETURN QUERY SELECT 'gold.market_metrics'::TEXT, gold.refresh_market_metrics();
    RETURN QUERY SELECT 'consumption.dashboard'::TEXT, consumption.refresh_dashboard_summary();
    INSERT INTO bronze.ingestion_log (source, component, records_processed, status, completed_at)
    VALUES ('pipeline', 'hourly_refresh', 0, 'success', NOW());
END;
$$;


--
-- Name: generate_inside_day_signals(date); Type: FUNCTION; Schema: gold; Owner: -
--

CREATE FUNCTION gold.generate_inside_day_signals(p_date date DEFAULT CURRENT_DATE) RETURNS TABLE(ticker character varying, signal_date date, entry_price numeric, target_price numeric, stop_price numeric, position_size_pct numeric, max_hold_days integer, strategy_id character varying, signal_strength integer)
    LANGUAGE plpgsql
    AS $$
BEGIN
    RETURN QUERY
    WITH daily_data AS (
        SELECT 
            up.ticker,
            up.date,
            up.high,
            up.low,
            up.close,
            up.volume,
            LAG(up.high) OVER (PARTITION BY up.ticker ORDER BY up.date) as prev_high,
            LAG(up.low) OVER (PARTITION BY up.ticker ORDER BY up.date) as prev_low,
            AVG(up.volume) OVER (
                PARTITION BY up.ticker 
                ORDER BY up.date 
                ROWS BETWEEN 19 PRECEDING AND 1 PRECEDING
            ) as avg_volume_20
        FROM silver.unified_prices up
        WHERE up.date >= p_date - INTERVAL '30 days'
          AND up.date <= p_date
    )
    SELECT 
        dd.ticker,
        dd.date::DATE as signal_date,
        dd.close as entry_price,
        ROUND(dd.close * 1.05, 4) as target_price,
        dd.close as stop_price,
        2.00 as position_size_pct,
        5 as max_hold_days,
        'inside_day_breakout'::VARCHAR(50) as strategy_id,
        CASE 
            WHEN dd.volume > dd.avg_volume_20 * 2.5 THEN 3
            WHEN dd.volume > dd.avg_volume_20 * 2.0 THEN 2
            ELSE 1
        END as signal_strength
    FROM daily_data dd
    WHERE dd.date = p_date
      AND dd.high < dd.prev_high
      AND dd.low > dd.prev_low
      AND dd.volume > dd.avg_volume_20 * 2.0
      AND dd.close > dd.prev_high * 1.02
      AND dd.prev_high IS NOT NULL
    ORDER BY dd.volume / dd.avg_volume_20 DESC;
END;
$$;


--
-- Name: refresh_market_metrics(); Type: FUNCTION; Schema: gold; Owner: -
--

CREATE FUNCTION gold.refresh_market_metrics() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE v_inserted INTEGER := 0;
BEGIN
    INSERT INTO gold.market_metrics (ticker, date, close_price, daily_change_pct, volume, trend_regime, volatility_regime, calculated_at)
    SELECT up.ticker, up.date, up.close as close_price, up.returns_1d * 100 as daily_change_pct, up.volume::BIGINT as volume,
        CASE WHEN up.close > ti.sma_50 AND ti.sma_50 > ti.sma_200 THEN 'UPTREND' WHEN up.close < ti.sma_50 AND ti.sma_50 < ti.sma_200 THEN 'DOWNTREND' ELSE 'RANGE' END as trend_regime,
        CASE WHEN ti.atr_14 / NULLIF(up.close, 0) > 0.03 THEN 'HIGH' WHEN ti.atr_14 / NULLIF(up.close, 0) < 0.01 THEN 'LOW' ELSE 'NORMAL' END as volatility_regime,
        NOW() as calculated_at
    FROM silver.unified_prices up LEFT JOIN silver.technical_indicators ti ON up.ticker = ti.ticker AND up.date = ti.date WHERE up.date >= CURRENT_DATE - INTERVAL '5 years'
    ON CONFLICT (ticker, date) DO UPDATE SET close_price = EXCLUDED.close_price, daily_change_pct = EXCLUDED.daily_change_pct, trend_regime = EXCLUDED.trend_regime, volatility_regime = EXCLUDED.volatility_regime, calculated_at = NOW()
    WHERE EXCLUDED.close_price IS DISTINCT FROM gold.market_metrics.close_price;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    RETURN v_inserted;
END;
$$;


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: gold; Owner: -
--

CREATE FUNCTION gold.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$;


--
-- Name: claim_task(integer, character varying); Type: FUNCTION; Schema: shared; Owner: -
--

CREATE FUNCTION shared.claim_task(p_task_id integer, p_agent character varying) RETURNS boolean
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE shared.agent_tasks 
    SET status = 'in_progress', updated_at = NOW()
    WHERE id = p_task_id AND status = 'pending' AND to_agent = p_agent;
    RETURN FOUND;
END;
$$;


--
-- Name: complete_task(integer, jsonb, text); Type: FUNCTION; Schema: shared; Owner: -
--

CREATE FUNCTION shared.complete_task(p_task_id integer, p_response jsonb, p_error text DEFAULT NULL::text) RETURNS void
    LANGUAGE plpgsql
    AS $$
BEGIN
    UPDATE shared.agent_tasks 
    SET status = CASE WHEN p_error IS NULL THEN 'completed' ELSE 'failed' END,
        response = p_response, error_message = p_error,
        completed_at = NOW(), updated_at = NOW()
    WHERE id = p_task_id;
END;
$$;


--
-- Name: refresh_unified_prices(); Type: FUNCTION; Schema: silver; Owner: -
--

CREATE FUNCTION silver.refresh_unified_prices() RETURNS integer
    LANGUAGE plpgsql
    AS $$
DECLARE v_inserted INTEGER := 0;
BEGIN
    INSERT INTO silver.unified_prices (ticker, asset_class, market, date, open, high, low, close, volume, adjusted_close, primary_source, all_sources, created_at)
    SELECT fmp.ticker, COALESCE(ar.asset_class, 'STOCK'), COALESCE(ar.market, 'US'), fmp.date, fmp.open, fmp.high, fmp.low, fmp.close, fmp.volume::DECIMAL, fmp.adjusted_close, 'fmp' as primary_source, jsonb_build_object('fmp', jsonb_build_object('close', fmp.close, 'volume', fmp.volume)), fmp.ingested_at
    FROM bronze.fmp_prices fmp LEFT JOIN silver.asset_registry ar ON fmp.ticker = ar.ticker WHERE fmp.ingested_at >= NOW() - INTERVAL '25 hours'
    ON CONFLICT (ticker, date) DO UPDATE SET close = EXCLUDED.close, volume = EXCLUDED.volume, adjusted_close = EXCLUDED.adjusted_close, all_sources = silver.unified_prices.all_sources || EXCLUDED.all_sources, updated_at = NOW()
    WHERE EXCLUDED.close IS DISTINCT FROM silver.unified_prices.close;
    GET DIAGNOSTICS v_inserted = ROW_COUNT;
    RETURN v_inserted;
END;
$$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: binance_crypto_ohlcv; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.binance_crypto_ohlcv (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    "interval" character varying(10) NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    open numeric(18,8),
    high numeric(18,8),
    low numeric(18,8),
    close numeric(18,8),
    volume numeric(18,8),
    quote_volume numeric(24,8),
    trades_count integer,
    taker_buy_volume numeric(18,8),
    taker_buy_quote_volume numeric(24,8),
    raw_data jsonb,
    ingested_at timestamp without time zone DEFAULT now()
);


--
-- Name: binance_crypto_ohlcv_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.binance_crypto_ohlcv_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: binance_crypto_ohlcv_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.binance_crypto_ohlcv_id_seq OWNED BY bronze.binance_crypto_ohlcv.id;


--
-- Name: binance_funding_rates; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.binance_funding_rates (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    funding_time timestamp without time zone NOT NULL,
    funding_rate numeric(18,8),
    mark_price numeric(18,8),
    raw_data jsonb,
    ingested_at timestamp without time zone DEFAULT now()
);


--
-- Name: binance_funding_rates_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.binance_funding_rates_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: binance_funding_rates_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.binance_funding_rates_id_seq OWNED BY bronze.binance_funding_rates.id;


--
-- Name: data_quality_log; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.data_quality_log (
    id bigint NOT NULL,
    source_table character varying(100) NOT NULL,
    ticker character varying(50),
    record_date date,
    issue_type character varying(50) NOT NULL,
    details text,
    raw_data jsonb,
    logged_at timestamp with time zone DEFAULT now()
);


--
-- Name: data_quality_log_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.data_quality_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: data_quality_log_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.data_quality_log_id_seq OWNED BY bronze.data_quality_log.id;


--
-- Name: earnings_calendar; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.earnings_calendar (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    earnings_date date NOT NULL,
    fiscal_quarter character varying(10),
    fiscal_year integer,
    eps_estimate double precision,
    revenue_estimate double precision,
    eps_actual double precision,
    revenue_actual double precision,
    eps_surprise double precision,
    eps_surprise_pct double precision,
    revenue_surprise double precision,
    price_pre_earnings double precision,
    price_post_earnings double precision,
    earnings_return double precision,
    source character varying(50) DEFAULT 'yfinance'::character varying,
    reported_at timestamp without time zone,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: earnings_calendar_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.earnings_calendar_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: earnings_calendar_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.earnings_calendar_id_seq OWNED BY bronze.earnings_calendar.id;


--
-- Name: fmp_institutional_holdings; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.fmp_institutional_holdings (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    holder_name character varying(200) NOT NULL,
    shares bigint,
    shares_change bigint,
    pct_out numeric(5,2),
    pct_held numeric(5,2),
    value bigint,
    report_date date,
    raw_data jsonb,
    ingested_at timestamp without time zone DEFAULT now()
);


--
-- Name: fmp_institutional_holdings_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.fmp_institutional_holdings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fmp_institutional_holdings_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.fmp_institutional_holdings_id_seq OWNED BY bronze.fmp_institutional_holdings.id;


--
-- Name: fred_macro_indicators; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.fred_macro_indicators (
    series_id character varying NOT NULL,
    indicator_name character varying,
    units character varying,
    frequency character varying,
    date date NOT NULL,
    value numeric,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: fx_prices; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.fx_prices (
    id integer NOT NULL,
    pair character varying(10) NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    open numeric(15,6),
    high numeric(15,6),
    low numeric(15,6),
    close numeric(15,6),
    volume bigint,
    source character varying(20),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: fx_prices_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.fx_prices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fx_prices_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.fx_prices_id_seq OWNED BY bronze.fx_prices.id;


--
-- Name: hkex_ipo_calendar_raw; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.hkex_ipo_calendar_raw (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    stock_name character varying(200),
    listing_date date NOT NULL,
    offer_price numeric(18,4),
    market_cap_hkd numeric(18,2),
    sector character varying(100),
    sub_sector character varying(100),
    sponsor character varying(200),
    shares_offered bigint,
    scraped_at timestamp with time zone DEFAULT now()
);


--
-- Name: hkex_ipo_calendar_raw_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.hkex_ipo_calendar_raw_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hkex_ipo_calendar_raw_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.hkex_ipo_calendar_raw_id_seq OWNED BY bronze.hkex_ipo_calendar_raw.id;


--
-- Name: ibkr_account_summary; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_account_summary (
    account character varying(50) NOT NULL,
    net_liquidation numeric(20,4),
    cash_hkd numeric(20,4),
    cash_usd numeric(20,4),
    available_funds numeric(20,4),
    buying_power numeric(20,4),
    position_count integer,
    fetched_at timestamp without time zone
);


--
-- Name: ibkr_contracts; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_contracts (
    id integer NOT NULL,
    con_id bigint NOT NULL,
    symbol character varying(16) NOT NULL,
    sec_type character varying(8) NOT NULL,
    exchange character varying(16),
    primary_exchange character varying(16),
    currency character varying(4),
    local_symbol character varying(32),
    trading_class character varying(16),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: ibkr_contracts_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.ibkr_contracts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_contracts_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.ibkr_contracts_id_seq OWNED BY bronze.ibkr_contracts.id;


--
-- Name: ibkr_fx_bars; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_fx_bars (
    id integer NOT NULL,
    pair character varying(10) NOT NULL,
    bar_size character varying(20) NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    open_bid numeric(18,8),
    high_bid numeric(18,8),
    low_bid numeric(18,8),
    close_bid numeric(18,8),
    volume numeric(18,4),
    ingested_at timestamp with time zone DEFAULT now()
);


--
-- Name: ibkr_fx_bars_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.ibkr_fx_bars_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_fx_bars_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.ibkr_fx_bars_id_seq OWNED BY bronze.ibkr_fx_bars.id;


--
-- Name: ibkr_fx_ticks; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_fx_ticks (
    id integer NOT NULL,
    pair character varying(10) NOT NULL,
    "timestamp" timestamp with time zone NOT NULL,
    bid numeric(18,8),
    ask numeric(18,8),
    ingested_at timestamp with time zone DEFAULT now()
);


--
-- Name: ibkr_fx_ticks_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.ibkr_fx_ticks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_fx_ticks_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.ibkr_fx_ticks_id_seq OWNED BY bronze.ibkr_fx_ticks.id;


--
-- Name: ibkr_historical_bars; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_historical_bars (
    id bigint NOT NULL,
    con_id bigint NOT NULL,
    bar_time timestamp with time zone NOT NULL,
    open numeric(18,8) NOT NULL,
    high numeric(18,8) NOT NULL,
    low numeric(18,8) NOT NULL,
    close numeric(18,8) NOT NULL,
    volume bigint,
    bar_size character varying(8) NOT NULL,
    what_to_show character varying(16) NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: ibkr_historical_bars_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.ibkr_historical_bars_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_historical_bars_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.ibkr_historical_bars_id_seq OWNED BY bronze.ibkr_historical_bars.id;


--
-- Name: ibkr_orders; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_orders (
    id integer NOT NULL,
    account character varying(50),
    order_id bigint,
    client_id bigint,
    perm_id bigint,
    ticker character varying(50),
    action character varying(20),
    quantity numeric(18,4),
    order_type character varying(20),
    limit_price numeric(18,4),
    aux_price numeric(18,4),
    tif character varying(10),
    status character varying(50),
    filled numeric(18,4),
    remaining numeric(18,4),
    avg_fill_price numeric(18,4),
    last_fill_price numeric(18,4),
    commission numeric(18,4),
    realized_pnl numeric(18,4),
    submit_time timestamp with time zone,
    execution_time timestamp with time zone,
    gtc boolean DEFAULT false,
    exchange character varying(20),
    currency character varying(10),
    con_id bigint,
    local_symbol character varying(50),
    notes text,
    raw_json jsonb,
    fetched_at timestamp with time zone DEFAULT now()
);


--
-- Name: ibkr_orders_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.ibkr_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.ibkr_orders_id_seq OWNED BY bronze.ibkr_orders.id;


--
-- Name: ibkr_positions; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_positions (
    id integer NOT NULL,
    account character varying(16) NOT NULL,
    con_id bigint NOT NULL,
    symbol character varying(16) NOT NULL,
    sec_type character varying(8) NOT NULL,
    exchange character varying(16),
    currency character varying(4),
    "position" numeric(18,4) NOT NULL,
    avg_cost numeric(18,8),
    recorded_at timestamp with time zone DEFAULT now()
);


--
-- Name: ibkr_positions_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.ibkr_positions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_positions_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.ibkr_positions_id_seq OWNED BY bronze.ibkr_positions.id;


--
-- Name: ibkr_positions_live; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.ibkr_positions_live (
    id integer NOT NULL,
    account character varying(50) NOT NULL,
    ticker character varying(20) NOT NULL,
    conid integer,
    asset_class character varying(20),
    quantity numeric(18,4),
    avg_cost numeric(18,4),
    market_price numeric(18,4),
    market_value numeric(18,4),
    unrealized_pnl numeric(18,4),
    unrealized_pnl_pct numeric(18,4),
    currency character varying(10),
    exchange character varying(20),
    fetched_at timestamp with time zone DEFAULT now()
);


--
-- Name: ibkr_positions_live_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.ibkr_positions_live_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_positions_live_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.ibkr_positions_live_id_seq OWNED BY bronze.ibkr_positions_live.id;


--
-- Name: institutional_holdings; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.institutional_holdings (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    report_date date NOT NULL,
    filing_date date,
    institutional_holders integer,
    institutional_pct double precision,
    insider_pct double precision,
    top_holder_name character varying(200),
    top_holder_pct double precision,
    shares_outstanding bigint,
    institutional_shares bigint,
    shares_change_qoq bigint,
    holders_change_qoq integer,
    new_positions integer,
    closed_positions integer,
    accumulation_score double precision,
    source character varying(50) DEFAULT 'yfinance'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.institutional_holdings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.institutional_holdings_id_seq OWNED BY bronze.institutional_holdings.id;


--
-- Name: manual_earnings; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.manual_earnings (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    report_date date NOT NULL,
    fiscal_quarter character varying(10),
    eps_estimate numeric(18,8),
    eps_actual numeric(18,8),
    revenue_estimate bigint,
    revenue_actual bigint,
    source_notes text,
    entered_by character varying(100),
    raw_data jsonb,
    ingested_at timestamp without time zone DEFAULT now()
);


--
-- Name: manual_earnings_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.manual_earnings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: manual_earnings_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.manual_earnings_id_seq OWNED BY bronze.manual_earnings.id;


--
-- Name: nfp_consensus_proxy; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.nfp_consensus_proxy (
    date date NOT NULL,
    actual numeric,
    forecast numeric,
    surprise numeric,
    source text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: raw_news; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.raw_news (
    date timestamp without time zone NOT NULL,
    id integer NOT NULL,
    category character varying(50),
    entity_name character varying(100),
    headline text,
    source character varying(100),
    raw_content text,
    ingested_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: raw_news_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.raw_news_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: raw_news_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.raw_news_id_seq OWNED BY bronze.raw_news.id;


--
-- Name: raw_stock_data; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.raw_stock_data (
    date timestamp without time zone NOT NULL,
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision,
    ingested_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    asset_category character varying(20)
);


--
-- Name: raw_stock_data_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.raw_stock_data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: raw_stock_data_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.raw_stock_data_id_seq OWNED BY bronze.raw_stock_data.id;


--
-- Name: yf_commodity_futures; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.yf_commodity_futures (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    name character varying(100),
    category character varying(50),
    exchange character varying(20),
    date date NOT NULL,
    open numeric(18,8),
    high numeric(18,8),
    low numeric(18,8),
    close numeric(18,8),
    volume bigint,
    adjusted_close numeric(18,8),
    raw_data jsonb,
    ingested_at timestamp without time zone DEFAULT now()
);


--
-- Name: yf_commodity_futures_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.yf_commodity_futures_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: yf_commodity_futures_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.yf_commodity_futures_id_seq OWNED BY bronze.yf_commodity_futures.id;


--
-- Name: yf_prices; Type: TABLE; Schema: bronze; Owner: -
--

CREATE TABLE bronze.yf_prices (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    date date NOT NULL,
    open numeric(18,8),
    high numeric(18,8),
    low numeric(18,8),
    close numeric(18,8),
    volume bigint,
    adjusted_close numeric(18,8),
    dividends numeric(18,8),
    stock_splits numeric(10,4),
    raw_data jsonb,
    ingested_at timestamp without time zone DEFAULT now()
);


--
-- Name: yf_prices_id_seq; Type: SEQUENCE; Schema: bronze; Owner: -
--

CREATE SEQUENCE bronze.yf_prices_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: yf_prices_id_seq; Type: SEQUENCE OWNED BY; Schema: bronze; Owner: -
--

ALTER SEQUENCE bronze.yf_prices_id_seq OWNED BY bronze.yf_prices.id;


--
-- Name: agent_health; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.agent_health (
    id integer NOT NULL,
    agent_id text NOT NULL,
    last_run_at timestamp without time zone,
    last_event_type text,
    status text DEFAULT 'unknown'::text,
    experiments_processed_24h integer DEFAULT 0,
    experiments_passed_24h integer DEFAULT 0,
    avg_cycle_minutes numeric(8,2),
    last_error text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: agent_health_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.agent_health_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_health_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.agent_health_id_seq OWNED BY consumption.agent_health.id;


--
-- Name: commodities; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.commodities (
    id integer NOT NULL,
    "timestamp" timestamp without time zone,
    asset character varying(50),
    ticker character varying(20),
    action character varying(10),
    close_price double precision,
    daily_change double precision,
    est_1d character varying(20),
    est_7d character varying(20),
    est_1m character varying(20),
    stop_loss character varying(20),
    rr_ratio character varying(20),
    vol_category character varying(10),
    sparkline json,
    reasoning text,
    logic_badges json,
    confidence_drivers json,
    trad_confidence double precision,
    swarm_confidence double precision,
    win_rate double precision,
    strategy_tags json,
    candlestick_pattern character varying(100)
);


--
-- Name: commodities_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.commodities_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: commodities_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.commodities_id_seq OWNED BY consumption.commodities.id;


--
-- Name: commodity; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.commodity AS
 SELECT id,
    "timestamp" AS updated_at,
    asset,
    ticker,
    action,
    close_price,
    daily_change,
    est_1d,
    est_7d,
    est_1m,
    stop_loss,
    rr_ratio,
    vol_category,
    sparkline,
    reasoning,
    logic_badges,
    confidence_drivers,
    trad_confidence,
    swarm_confidence,
    win_rate,
    strategy_tags,
    candlestick_pattern
   FROM consumption.commodities;


--
-- Name: cot_snapshot; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.cot_snapshot (
    instrument character varying(50) NOT NULL,
    last_date date,
    report_date date,
    noncomm_long bigint,
    noncomm_short bigint,
    net_noncomm bigint,
    cot_z numeric(12,4),
    sentiment character varying(20),
    signal_flag integer,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: crypto_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.crypto_metrics (
    id integer NOT NULL,
    date timestamp without time zone NOT NULL,
    ticker character varying(20) NOT NULL,
    close_price double precision,
    log_return double precision,
    volume_24h bigint,
    market_cap_usd double precision,
    btc_dominance double precision,
    eth_gas_price_gwei double precision,
    hash_rate_th_s double precision,
    exchange_inflow_proxy double precision,
    exchange_outflow_proxy double precision,
    fear_greed_index integer,
    stablecoin_supply_ratio double precision,
    funding_rate double precision,
    open_interest_usd double precision,
    liquidations_24h_usd double precision,
    rsi_14 double precision,
    macd_histogram double precision,
    bollinger_width double precision,
    mvrv_z_score double precision,
    nvt_ratio double precision,
    prophet_forecast double precision,
    lsd_divergence_score double precision,
    candlestick_pattern character varying(100),
    candlestick_sentiment double precision
);


--
-- Name: crypto; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.crypto AS
 SELECT id,
    date,
    ticker,
    close_price,
    log_return,
    volume_24h,
    market_cap_usd,
    btc_dominance,
    eth_gas_price_gwei,
    hash_rate_th_s,
    exchange_inflow_proxy,
    exchange_outflow_proxy,
    fear_greed_index,
    stablecoin_supply_ratio,
    funding_rate,
    open_interest_usd,
    liquidations_24h_usd,
    rsi_14,
    macd_histogram,
    bollinger_width,
    mvrv_z_score,
    nvt_ratio,
    prophet_forecast,
    lsd_divergence_score,
    candlestick_pattern,
    candlestick_sentiment
   FROM gold.crypto_metrics;


--
-- Name: crypto_funding_snapshot; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.crypto_funding_snapshot (
    symbol character varying(50) NOT NULL,
    last_date date,
    funding_rate_8h numeric(18,8),
    funding_z numeric(12,4),
    n_obs integer,
    regime character varying(20),
    signal_flag integer,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: dashboard_market_overview; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.dashboard_market_overview (
    id integer NOT NULL,
    region character varying(50) NOT NULL,
    index_name character varying(50),
    index_ticker character varying(20),
    current_value numeric(15,4),
    change_pct numeric(10,4),
    change_value numeric(15,4),
    trend character varying(20),
    sentiment_score numeric(5,2),
    volatility_index numeric(8,4),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: dashboard_market_overview_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.dashboard_market_overview_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dashboard_market_overview_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.dashboard_market_overview_id_seq OWNED BY consumption.dashboard_market_overview.id;


--
-- Name: dashboard_opportunities_top; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.dashboard_opportunities_top (
    id integer NOT NULL,
    ticker text NOT NULL,
    name text,
    sector text,
    signal_type text,
    score numeric,
    entry_price numeric,
    target_price numeric,
    stop_loss numeric,
    risk_reward numeric,
    updated_at timestamp with time zone DEFAULT now(),
    rank integer,
    asset_class text,
    direction text,
    confidence numeric,
    rationale text,
    catalyst text,
    timeframe text,
    technical_setup text,
    expected_return_pct numeric,
    take_profit numeric,
    position_size_pct numeric,
    strategy_id text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: dashboard_opportunities_top_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.dashboard_opportunities_top_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dashboard_opportunities_top_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.dashboard_opportunities_top_id_seq OWNED BY consumption.dashboard_opportunities_top.id;


--
-- Name: dashboard_summary_cards; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.dashboard_summary_cards (
    id integer NOT NULL,
    card_key character varying(50) NOT NULL,
    card_title character varying(100) NOT NULL,
    value_display character varying(50),
    value_numeric numeric(18,8),
    change_pct numeric(10,4),
    change_display character varying(50),
    trend character varying(20),
    alert_level character varying(20),
    last_updated timestamp without time zone DEFAULT now()
);


--
-- Name: dashboard_summary_cards_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.dashboard_summary_cards_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: dashboard_summary_cards_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.dashboard_summary_cards_id_seq OWNED BY consumption.dashboard_summary_cards.id;


--
-- Name: fx_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.fx_metrics (
    id integer NOT NULL,
    date timestamp without time zone NOT NULL,
    ticker character varying(20) NOT NULL,
    close_price double precision,
    log_return double precision,
    interest_rate_diff double precision,
    dxy_correlation double precision,
    volatility_24h double precision,
    rsi_14 double precision,
    macd_histogram double precision,
    bollinger_width double precision,
    prophet_forecast double precision,
    market_regime character varying(20),
    candlestick_pattern character varying(100),
    candlestick_sentiment double precision,
    stoch_k numeric(8,4),
    stoch_d numeric(8,4),
    stoch_oversold boolean,
    stoch_overbought boolean,
    adx numeric(8,4),
    adx_plus_di numeric(8,4),
    adx_minus_di numeric(8,4),
    adx_trend_strength character varying(20),
    psar numeric(12,4),
    psar_direction character varying(10),
    psar_flip boolean,
    macd_line numeric(12,4),
    macd_signal numeric(12,4),
    open numeric,
    high numeric,
    low numeric,
    atr_14 numeric,
    volatility_20d numeric,
    sma_5 numeric,
    sma_20 numeric,
    sma_50 numeric
);


--
-- Name: fx; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.fx AS
 SELECT id,
    date,
    ticker,
    close_price,
    log_return,
    interest_rate_diff,
    dxy_correlation,
    volatility_24h,
    rsi_14,
    macd_histogram,
    bollinger_width,
    prophet_forecast,
    market_regime,
    candlestick_pattern,
    candlestick_sentiment,
    stoch_k,
    stoch_d,
    stoch_oversold,
    stoch_overbought,
    adx,
    adx_plus_di,
    adx_minus_di,
    adx_trend_strength,
    psar,
    psar_direction,
    psar_flip,
    macd_line,
    macd_signal,
    open,
    high,
    low,
    atr_14,
    volatility_20d,
    sma_5,
    sma_20,
    sma_50
   FROM gold.fx_metrics;


--
-- Name: global_state; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.global_state (
    id integer NOT NULL,
    key character varying(100),
    value text,
    category character varying(50),
    "timestamp" timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    rationale text,
    estimates jsonb
);


--
-- Name: global_state_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.global_state_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: global_state_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.global_state_id_seq OWNED BY consumption.global_state.id;


--
-- Name: hft_matrix; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.hft_matrix (
    "timestamp" timestamp without time zone NOT NULL,
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    asset_class character varying(20),
    liquidity_momentum character varying(20),
    fusion_signal character varying(20),
    shock_warning character varying(20),
    pressure_value double precision,
    reasoning text,
    velocity_estimates jsonb
);


--
-- Name: hft_matrix_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.hft_matrix_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hft_matrix_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.hft_matrix_id_seq OWNED BY consumption.hft_matrix.id;


--
-- Name: hk_ipo_calendar; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.hk_ipo_calendar (
    ticker character varying(20) NOT NULL,
    stock_name character varying(255) NOT NULL,
    listing_date date NOT NULL,
    offer_price numeric(10,4) NOT NULL,
    currency character varying(3) DEFAULT 'HKD'::character varying,
    market_cap_hkd numeric(20,2),
    market_cap_usd numeric(20,2),
    sector character varying(100),
    sub_sector character varying(100),
    sponsor character varying(255),
    underwriters text[],
    shares_offered bigint,
    greenshoe_shares bigint,
    board character varying(20),
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: hk_ipo_details; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.hk_ipo_details (
    ticker character varying(20) NOT NULL,
    oversubscription_retail numeric(10,2),
    oversubscription_institutional numeric(10,2),
    oversubscription_total numeric(10,2),
    cornerstone_total_pct numeric(5,2),
    cornerstone_investors jsonb,
    cornerstone_lockup_avg_days integer,
    lockup_period_days integer,
    greenshoe_pct numeric(5,2),
    use_of_proceeds text,
    application_start date,
    application_end date,
    price_fixing_date date,
    allotment_date date,
    listing_date date,
    lockup_expiry_date date,
    prospectus_url text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: hk_ipo_performance; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.hk_ipo_performance (
    ticker character varying(20) NOT NULL,
    listing_date date NOT NULL,
    offer_price numeric(10,4) NOT NULL,
    first_day_open numeric(10,4),
    first_day_close numeric(10,4),
    first_day_volume bigint,
    first_day_return_pct numeric(10,4),
    return_day3_pct numeric(10,4),
    return_day5_pct numeric(10,4),
    return_day10_pct numeric(10,4),
    return_day20_pct numeric(10,4),
    return_day30_pct numeric(10,4),
    return_day60_pct numeric(10,4),
    return_day90_pct numeric(10,4),
    current_price numeric(10,4),
    total_return_pct numeric(10,4),
    high_since_listing numeric(10,4),
    low_since_listing numeric(10,4),
    max_drawdown_pct numeric(10,4),
    performance_tier character varying(20),
    vs_ipo_index_return_pct numeric(10,4),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: hkex_ipo_sector_performance; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.hkex_ipo_sector_performance AS
 SELECT c.sector,
    count(*) AS ipo_count,
    avg(p.first_day_return_pct) AS avg_first_day_return,
    avg(p.return_day30_pct) AS avg_day30_return,
    avg(d.oversubscription_retail) AS avg_oversubscription,
    (((count(
        CASE
            WHEN (p.first_day_return_pct > (0)::numeric) THEN 1
            ELSE NULL::integer
        END))::numeric / (count(*))::numeric) * (100)::numeric) AS win_rate
   FROM ((gold.hk_ipo_calendar c
     JOIN gold.hk_ipo_performance p ON (((c.ticker)::text = (p.ticker)::text)))
     LEFT JOIN gold.hk_ipo_details d ON (((c.ticker)::text = (d.ticker)::text)))
  WHERE (c.listing_date >= (CURRENT_DATE - '2 years'::interval))
  GROUP BY c.sector
  ORDER BY (avg(p.first_day_return_pct)) DESC NULLS LAST;


--
-- Name: index_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.index_metrics (
    date date NOT NULL,
    ticker character varying(20) NOT NULL,
    name character varying(100),
    market character varying(10),
    region character varying(20),
    currency character varying(10),
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    change_pct numeric,
    change_amount numeric,
    ytd_change numeric,
    ma_50 numeric,
    ma_200 numeric,
    above_ma_50 boolean,
    above_ma_200 boolean,
    golden_cross boolean,
    rsi_14 numeric,
    macd_line numeric,
    macd_signal numeric,
    macd_hist numeric,
    atr_14 numeric,
    _52_week_high numeric,
    _52_week_low numeric,
    _52_week_range_pct numeric,
    returns_1d numeric,
    returns_5d numeric,
    returns_21d numeric,
    returns_63d numeric,
    returns_252d numeric,
    volatility_21d numeric,
    is_volatility_index boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: index_metrics; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.index_metrics AS
 SELECT date,
    ticker,
    name,
    market,
    (region)::character varying(50) AS region,
    currency,
    open,
    high,
    low,
    close,
    volume,
    change_pct,
    change_amount,
    ytd_change,
    ma_50,
    ma_200,
    above_ma_50,
    above_ma_200,
    golden_cross,
    rsi_14,
    macd_line,
    macd_signal,
    macd_hist,
    atr_14,
    _52_week_high,
    _52_week_low,
    _52_week_range_pct,
    returns_1d,
    returns_5d,
    returns_21d,
    returns_63d,
    returns_252d,
    volatility_21d,
    is_volatility_index,
        CASE
            WHEN (change_pct > (0)::numeric) THEN 'positive'::text
            WHEN (change_pct < (0)::numeric) THEN 'negative'::text
            ELSE 'neutral'::text
        END AS trend_direction
   FROM gold.index_metrics
  ORDER BY date DESC, ((region)::character varying(50)), market, ticker;


--
-- Name: macro_calendar_dashboard; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.macro_calendar_dashboard (
    date date NOT NULL,
    cpi_flag integer,
    nfp_flag integer,
    fed_funds_flag integer,
    event_flag integer,
    event_count integer,
    severity character varying(20),
    days_until integer,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: market; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.market AS
 SELECT id,
    region,
    index_name,
    index_ticker,
    current_value,
    change_pct,
    change_value,
    trend,
    sentiment_score,
    volatility_index,
    updated_at
   FROM consumption.dashboard_market_overview;


--
-- Name: market_data_snapshot; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.market_data_snapshot (
    ticker character varying(50) NOT NULL,
    asset_class character varying(50),
    last_date date,
    last_close numeric(18,8),
    last_volume bigint,
    returns_1d numeric(12,6),
    returns_5d numeric(12,6),
    returns_21d numeric(12,6),
    primary_source character varying(50),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: markets_commodities_overview; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.markets_commodities_overview (
    id integer NOT NULL,
    ticker character varying(50) NOT NULL,
    name character varying(100),
    category character varying(50),
    exchange character varying(20),
    price numeric(15,4),
    change_pct numeric(10,4),
    trend character varying(20),
    rsi_14 numeric(6,2),
    current_month_bias character varying(20),
    next_month_bias character varying(20),
    seasonal_strength numeric(4,3),
    signal character varying(10),
    signal_strength numeric(4,3),
    strategy_signals jsonb,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: markets_commodities_overview_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.markets_commodities_overview_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: markets_commodities_overview_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.markets_commodities_overview_id_seq OWNED BY consumption.markets_commodities_overview.id;


--
-- Name: markets_indices_overview; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.markets_indices_overview AS
 SELECT ticker,
    name,
    market,
    (region)::character varying(50) AS region,
    currency,
    date,
    close AS price,
    change_pct,
    change_amount,
    ytd_change,
    _52_week_high,
    _52_week_low,
    _52_week_range_pct,
    ma_50,
    ma_200,
    above_ma_50,
    above_ma_200,
    rsi_14,
    is_volatility_index,
        CASE
            WHEN (change_pct > (0)::numeric) THEN 'positive'::text
            WHEN (change_pct < (0)::numeric) THEN 'negative'::text
            ELSE 'neutral'::text
        END AS trend_direction
   FROM gold.index_metrics
  WHERE (date = ( SELECT max(index_metrics_1.date) AS max
           FROM gold.index_metrics index_metrics_1))
  ORDER BY ((region)::character varying(50)), market, ticker;


--
-- Name: markets_stocks_overview; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.markets_stocks_overview (
    id integer NOT NULL,
    ticker character varying(50) NOT NULL,
    name character varying(200),
    sector character varying(100),
    industry character varying(100),
    market character varying(20),
    price numeric(15,4),
    change_pct numeric(10,4),
    change_value numeric(10,4),
    volume bigint,
    avg_volume bigint,
    volume_ratio numeric(5,2),
    trend character varying(20),
    rsi_14 numeric(6,2),
    distance_to_52w_high_pct numeric(10,4),
    distance_to_52w_low_pct numeric(10,4),
    market_cap bigint,
    pe_ratio numeric(10,4),
    forward_pe numeric(10,4),
    pb_ratio numeric(10,4),
    dividend_yield numeric(6,4),
    strategy_signals jsonb,
    top_strategy_score numeric(6,4),
    updated_at timestamp without time zone DEFAULT now(),
    signal character varying(10),
    signal_strength numeric(4,3),
    asset_class character varying(20)
);


--
-- Name: markets_stocks_overview_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.markets_stocks_overview_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: markets_stocks_overview_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.markets_stocks_overview_id_seq OWNED BY consumption.markets_stocks_overview.id;


--
-- Name: performance_monthly_returns; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.performance_monthly_returns (
    id integer NOT NULL,
    portfolio_type character varying(20) NOT NULL,
    year integer NOT NULL,
    month integer NOT NULL,
    return_pct numeric(10,4),
    benchmark_return_pct numeric(10,4),
    excess_return_pct numeric(10,4)
);


--
-- Name: performance_monthly_returns_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.performance_monthly_returns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: performance_monthly_returns_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.performance_monthly_returns_id_seq OWNED BY consumption.performance_monthly_returns.id;


--
-- Name: performance_strategy_attribution; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.performance_strategy_attribution (
    id integer NOT NULL,
    strategy_id character varying(50) NOT NULL,
    strategy_name character varying(100),
    portfolio_type character varying(20),
    allocated_capital_pct numeric(5,2),
    contribution_pct numeric(10,4),
    return_pct numeric(10,4),
    num_trades integer,
    win_rate numeric(5,4),
    avg_trade_return_pct numeric(10,4),
    max_drawdown_pct numeric(10,4),
    sharpe_ratio numeric(6,3),
    calmar_ratio numeric(6,3),
    calculated_at timestamp without time zone DEFAULT now()
);


--
-- Name: performance_strategy_attribution_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.performance_strategy_attribution_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: performance_strategy_attribution_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.performance_strategy_attribution_id_seq OWNED BY consumption.performance_strategy_attribution.id;


--
-- Name: portfolio_positions_current; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.portfolio_positions_current (
    id integer NOT NULL,
    strategy_id character varying(20),
    ticker character varying(20) NOT NULL,
    side character varying(10) DEFAULT 'LONG'::character varying,
    entry_date date,
    entry_price numeric(15,4),
    current_price numeric(15,4),
    quantity numeric(15,4),
    market_value numeric(15,2),
    weight_pct numeric(5,2),
    unrealized_pnl numeric(15,2),
    realized_pnl numeric(15,2),
    status character varying(20) DEFAULT 'OPEN'::character varying,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: portfolio_positions_current_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.portfolio_positions_current_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: portfolio_positions_current_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.portfolio_positions_current_id_seq OWNED BY consumption.portfolio_positions_current.id;


--
-- Name: portfolio_risk_metrics; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.portfolio_risk_metrics (
    id integer NOT NULL,
    portfolio_type character varying(20) NOT NULL,
    gross_exposure_pct numeric(10,4),
    net_exposure_pct numeric(10,4),
    long_exposure_pct numeric(10,4),
    short_exposure_pct numeric(10,4),
    cash_pct numeric(10,4),
    top_5_concentration_pct numeric(5,2),
    top_10_concentration_pct numeric(5,2),
    herfindahl_index numeric(6,4),
    portfolio_beta numeric(8,4),
    var_95_daily numeric(18,8),
    var_95_pct numeric(10,4),
    expected_shortfall numeric(18,8),
    volatility_annual numeric(10,4),
    stress_bear_scenario_pct numeric(10,4),
    stress_crash_scenario_pct numeric(10,4),
    calculated_at timestamp without time zone DEFAULT now()
);


--
-- Name: portfolio_risk_metrics_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.portfolio_risk_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: portfolio_risk_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.portfolio_risk_metrics_id_seq OWNED BY consumption.portfolio_risk_metrics.id;


--
-- Name: promoted_strategies; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.promoted_strategies (
    id integer NOT NULL,
    strategy_id text NOT NULL,
    experiment_id text NOT NULL,
    generation integer,
    sharpe_oos numeric(8,4),
    max_drawdown numeric(8,4),
    trade_count_oos integer,
    risk_score numeric(5,2),
    param_set jsonb,
    promoted_at timestamp without time zone,
    production_strategy_id character varying(10),
    status text DEFAULT 'available'::text,
    notes text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: promoted_strategies_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.promoted_strategies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: promoted_strategies_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.promoted_strategies_id_seq OWNED BY consumption.promoted_strategies.id;


--
-- Name: research_contrarian_signals; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.research_contrarian_signals (
    id integer NOT NULL,
    ticker character varying(50) NOT NULL,
    name character varying(200),
    signal_type character varying(50),
    contrarian_score numeric(5,2),
    signal_direction character varying(20),
    confidence numeric(4,3),
    metric_1_name character varying(50),
    metric_1_value numeric(18,8),
    metric_1_percentile integer,
    metric_2_name character varying(50),
    metric_2_value numeric(18,8),
    metric_2_percentile integer,
    metric_3_name character varying(50),
    metric_3_value numeric(18,8),
    metric_3_percentile integer,
    narrative text,
    key_insight text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: research_contrarian_signals_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.research_contrarian_signals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: research_contrarian_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.research_contrarian_signals_id_seq OWNED BY consumption.research_contrarian_signals.id;


--
-- Name: research_pipeline; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.research_pipeline (
    id integer NOT NULL,
    experiment_id text NOT NULL,
    generation integer DEFAULT 1,
    parent_experiment_id text,
    strategy_type text,
    param_set jsonb,
    pipeline_stage text,
    stage_started_at timestamp without time zone,
    sharpe_oos numeric(8,4),
    max_drawdown numeric(8,4),
    risk_approved boolean,
    qa_passed boolean,
    rejection_reason text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: research_pipeline_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.research_pipeline_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: research_pipeline_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.research_pipeline_id_seq OWNED BY consumption.research_pipeline.id;


--
-- Name: research_seasonality_patterns; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.research_seasonality_patterns (
    id integer NOT NULL,
    ticker character varying(50) NOT NULL,
    name character varying(200),
    asset_class character varying(20),
    current_month integer,
    current_month_bias character varying(20),
    current_month_historical_return numeric(10,4),
    current_month_win_rate numeric(5,4),
    next_month integer,
    next_month_bias character varying(20),
    next_month_historical_return numeric(10,4),
    monthly_patterns_json jsonb,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: research_seasonality_patterns_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.research_seasonality_patterns_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: research_seasonality_patterns_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.research_seasonality_patterns_id_seq OWNED BY consumption.research_seasonality_patterns.id;


--
-- Name: research_sue_scores; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.research_sue_scores (
    id integer NOT NULL,
    ticker character varying(50) NOT NULL,
    name character varying(200),
    report_date date NOT NULL,
    eps_estimate numeric(12,4),
    eps_actual numeric(12,4),
    eps_surprise_pct numeric(10,4),
    sue_score numeric(18,8),
    sue_decile integer,
    sue_category character varying(50),
    price_change_1d numeric(10,4),
    price_change_3d numeric(10,4),
    price_change_5d numeric(10,4),
    drift_signal character varying(20),
    sector character varying(100),
    market_cap bigint,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: research_sue_scores_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.research_sue_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: research_sue_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.research_sue_scores_id_seq OWNED BY consumption.research_sue_scores.id;


--
-- Name: settings_data_sources; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.settings_data_sources (
    id integer NOT NULL,
    data_type character varying(50) NOT NULL,
    source_priority integer NOT NULL,
    source_name character varying(50) NOT NULL,
    is_active boolean DEFAULT true,
    fallback_source character varying(50),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: settings_data_sources_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.settings_data_sources_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: settings_data_sources_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.settings_data_sources_id_seq OWNED BY consumption.settings_data_sources.id;


--
-- Name: signal_logs; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.signal_logs (
    id integer NOT NULL,
    strategy_id smallint,
    signal_date date,
    signal smallint,
    logged_at timestamp without time zone DEFAULT now(),
    ticker character varying(20),
    signal_type character varying(20),
    signal_criteria text,
    confidence double precision
);


--
-- Name: signal_logs_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.signal_logs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: signal_logs_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.signal_logs_id_seq OWNED BY consumption.signal_logs.id;


--
-- Name: stock; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.stock AS
 SELECT id,
    ticker,
    name,
    sector,
    industry,
    market,
    price,
    change_pct,
    change_value,
    volume,
    avg_volume,
    volume_ratio,
    trend,
    rsi_14,
    distance_to_52w_high_pct,
    distance_to_52w_low_pct,
    market_cap,
    pe_ratio,
    forward_pe,
    pb_ratio,
    dividend_yield,
    strategy_signals,
    top_strategy_score,
    updated_at,
    signal,
    signal_strength,
    asset_class
   FROM consumption.markets_stocks_overview;


--
-- Name: strategies_backtest_results; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.strategies_backtest_results (
    id integer NOT NULL,
    strategy_id character varying(50) NOT NULL,
    sharpe_ratio numeric(6,3),
    max_drawdown_pct numeric(10,4),
    total_trades integer,
    win_rate numeric(5,4),
    asset_class character varying(50),
    sharpe_oos numeric,
    returns_oos numeric,
    max_drawdown_oos numeric,
    trade_count_oos integer,
    win_rate_oos numeric,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: strategies_backtest_results_id_seq; Type: SEQUENCE; Schema: consumption; Owner: -
--

CREATE SEQUENCE consumption.strategies_backtest_results_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategies_backtest_results_id_seq; Type: SEQUENCE OWNED BY; Schema: consumption; Owner: -
--

ALTER SEQUENCE consumption.strategies_backtest_results_id_seq OWNED BY consumption.strategies_backtest_results.id;


--
-- Name: strategy_scores_dynamic; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.strategy_scores_dynamic (
    strategy_id character varying(50) NOT NULL,
    score numeric(5,2),
    buy_signals jsonb DEFAULT '[]'::jsonb,
    sell_signals jsonb DEFAULT '[]'::jsonb,
    signal_strength numeric(4,3),
    last_updated timestamp without time zone DEFAULT now(),
    calculated_by character varying(50) DEFAULT 'v1.0'::character varying,
    ticker character varying(20) NOT NULL,
    CONSTRAINT strategy_scores_dynamic_score_check CHECK (((score >= (0)::numeric) AND (score <= (100)::numeric))),
    CONSTRAINT strategy_scores_dynamic_signal_strength_check CHECK (((signal_strength >= (0)::numeric) AND (signal_strength <= (1)::numeric)))
);


--
-- Name: TABLE strategy_scores_dynamic; Type: COMMENT; Schema: consumption; Owner: -
--

COMMENT ON TABLE consumption.strategy_scores_dynamic IS 'Dynamic scoring system for Lab tab - updated every 5-15 minutes';


--
-- Name: ticker_scores; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.ticker_scores (
    ticker character varying(20) NOT NULL,
    strategy_id character varying(50) NOT NULL,
    score numeric(5,2),
    criteria_met jsonb DEFAULT '{}'::jsonb,
    signal_action character varying(10),
    last_updated timestamp without time zone DEFAULT now(),
    CONSTRAINT ticker_scores_score_check CHECK (((score >= (0)::numeric) AND (score <= (100)::numeric))),
    CONSTRAINT ticker_scores_signal_action_check CHECK (((signal_action)::text = ANY ((ARRAY['BUY'::character varying, 'SELL'::character varying, 'HOLD'::character varying])::text[])))
);


--
-- Name: commodity_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.commodity_metrics (
    id integer NOT NULL,
    date timestamp without time zone NOT NULL,
    ticker character varying(20) NOT NULL,
    close_price double precision,
    log_return double precision,
    volume bigint,
    us_10y_real_yield double precision,
    dxy_close double precision,
    inflation_breakeven double precision,
    gold_silver_ratio double precision,
    sp500_correlation double precision,
    inventory_levels double precision,
    etf_holdings_tonnes double precision,
    cot_net_commercial double precision,
    cot_net_speculator double precision,
    rsi_14 double precision,
    macd_histogram double precision,
    bollinger_width double precision,
    seasonality_score double precision,
    prophet_forecast double precision,
    candlestick_pattern character varying(100),
    candlestick_sentiment double precision
);


--
-- Name: v_commodity_daily; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_commodity_daily AS
 SELECT DISTINCT ON (ticker, (date(date))) id,
    date(date) AS date,
    ticker,
    close_price,
    log_return,
    volume,
    us_10y_real_yield,
    dxy_close,
    inflation_breakeven,
    gold_silver_ratio,
    sp500_correlation,
    inventory_levels,
    etf_holdings_tonnes,
    cot_net_commercial,
    cot_net_speculator,
    rsi_14,
    macd_histogram,
    bollinger_width,
    seasonality_score,
    prophet_forecast,
    candlestick_pattern,
    candlestick_sentiment
   FROM gold.commodity_metrics
  ORDER BY ticker, (date(date));


--
-- Name: v_commodity_metrics; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_commodity_metrics AS
 SELECT date,
    ticker,
    close_price,
    volume,
    rsi_14,
    macd_histogram,
    bollinger_width,
    seasonality_score,
    candlestick_pattern,
    candlestick_sentiment
   FROM gold.v_commodity_daily
  ORDER BY ticker, date;


--
-- Name: v_dashboard_kpis; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_dashboard_kpis AS
 SELECT card_key,
    card_title,
    value_display,
    value_numeric,
    change_pct,
    change_display,
    trend,
    alert_level,
    last_updated
   FROM consumption.dashboard_summary_cards;


--
-- Name: v_dashboard_marketoverview; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_dashboard_marketoverview AS
 SELECT region,
    index_name,
    index_ticker,
    current_value,
    change_pct,
    trend,
    sentiment_score,
    updated_at
   FROM consumption.dashboard_market_overview;


--
-- Name: v_earnings_clean; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_earnings_clean AS
 SELECT id,
    ticker,
    earnings_date,
    fiscal_quarter,
    fiscal_year,
    eps_estimate,
    eps_actual,
        CASE
            WHEN (eps_surprise_pct > (1000)::double precision) THEN (1000)::double precision
            WHEN (eps_surprise_pct < ('-1000'::integer)::double precision) THEN ('-1000'::integer)::double precision
            WHEN ((eps_estimate IS NULL) OR (abs(eps_estimate) < (0.01)::double precision)) THEN NULL::double precision
            ELSE eps_surprise_pct
        END AS eps_surprise_pct_clean,
    eps_surprise_pct AS eps_surprise_pct_raw,
    revenue_estimate,
    revenue_actual,
    revenue_surprise,
    source,
    reported_at,
    created_at
   FROM bronze.earnings_calendar
  WHERE ((eps_actual IS NOT NULL) AND ((eps_estimate IS NOT NULL) OR (eps_surprise_pct IS NOT NULL)));


--
-- Name: v_earnings_clean; Type: VIEW; Schema: silver; Owner: -
--

CREATE VIEW silver.v_earnings_clean AS
 SELECT ticker AS symbol,
    earnings_date,
    eps_actual,
    eps_estimate,
    eps_surprise_pct,
        CASE
            WHEN (eps_surprise_pct > (5)::double precision) THEN 'beat'::text
            WHEN (eps_surprise_pct < ('-5'::integer)::double precision) THEN 'miss'::text
            ELSE 'inline'::text
        END AS surprise_category,
    revenue_actual,
    revenue_estimate,
    fiscal_quarter,
    source,
    reported_at AS ingested_at
   FROM bronze.earnings_calendar
  WHERE ((eps_actual IS NOT NULL) AND (eps_estimate IS NOT NULL) AND (eps_surprise_pct IS NOT NULL));


--
-- Name: v_earnings_history; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_earnings_history AS
 SELECT symbol,
    earnings_date,
    eps_actual,
    eps_estimate,
    eps_surprise_pct,
    revenue_actual,
    revenue_estimate,
    fiscal_quarter,
    source
   FROM silver.v_earnings_clean
  ORDER BY earnings_date DESC;


--
-- Name: earnings_signals; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.earnings_signals (
    id bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    earnings_date date NOT NULL,
    eps_surprise_pct numeric(10,4) NOT NULL,
    surprise_category character varying(10) NOT NULL,
    signal_window_start date,
    signal_window_end date,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: v_earnings_signals; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_earnings_signals AS
 SELECT symbol,
    earnings_date,
    eps_surprise_pct,
    surprise_category,
    signal_window_start,
    signal_window_end,
    created_at
   FROM gold.earnings_signals
  WHERE (eps_surprise_pct > (5)::numeric)
  ORDER BY earnings_date DESC, eps_surprise_pct DESC;


--
-- Name: interbank_rates; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.interbank_rates (
    id integer NOT NULL,
    date date NOT NULL,
    currency character varying(3) DEFAULT 'HKD'::character varying NOT NULL,
    tenor character varying(10) DEFAULT '1M'::character varying NOT NULL,
    rate numeric(10,5) NOT NULL,
    source character varying(50) DEFAULT 'HKMA'::character varying,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: v_hibor_1m; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_hibor_1m AS
 SELECT date,
    rate AS hibor_1m_rate,
    source
   FROM gold.interbank_rates
  WHERE (((currency)::text = 'HKD'::text) AND ((tenor)::text = '1M'::text))
  ORDER BY date;


--
-- Name: v_markets_commodities; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_markets_commodities AS
 SELECT ticker,
    name,
    category,
    exchange,
    price,
    change_pct,
    trend,
    current_month_bias,
    next_month_bias,
    seasonal_strength,
    signal,
    signal_strength,
    updated_at
   FROM consumption.markets_commodities_overview
  ORDER BY category, ticker;


--
-- Name: v_markets_stocks; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_markets_stocks AS
 SELECT ticker,
    name,
    sector,
    industry,
    market,
    price,
    change_pct,
    volume,
    trend,
    rsi_14,
    market_cap,
    pe_ratio,
    top_strategy_score,
    signal,
    signal_strength,
    updated_at
   FROM consumption.markets_stocks_overview
  ORDER BY top_strategy_score DESC NULLS LAST;


--
-- Name: v_performance_attribution; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_performance_attribution AS
 SELECT strategy_id,
    strategy_name,
    portfolio_type,
    allocated_capital_pct,
    contribution_pct,
    return_pct,
    num_trades,
    win_rate,
    avg_trade_return_pct,
    max_drawdown_pct,
    sharpe_ratio,
    calculated_at
   FROM consumption.performance_strategy_attribution
  ORDER BY return_pct DESC NULLS LAST;


--
-- Name: v_performance_monthlyreturns; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_performance_monthlyreturns AS
 SELECT portfolio_type,
    year,
    month,
    return_pct,
    benchmark_return_pct,
    excess_return_pct
   FROM consumption.performance_monthly_returns
  ORDER BY year DESC, month DESC;


--
-- Name: v_portfolio_risk; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_portfolio_risk AS
 SELECT portfolio_type,
    gross_exposure_pct,
    net_exposure_pct,
    long_exposure_pct,
    cash_pct,
    top_5_concentration_pct,
    top_10_concentration_pct,
    portfolio_beta,
    var_95_daily,
    var_95_pct,
    volatility_annual,
    stress_bear_scenario_pct,
    stress_crash_scenario_pct,
    calculated_at
   FROM consumption.portfolio_risk_metrics;


--
-- Name: v_research_contrarian; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_research_contrarian AS
 SELECT ticker,
    name,
    signal_type,
    contrarian_score,
    signal_direction,
    confidence,
    narrative,
    key_insight,
    updated_at
   FROM consumption.research_contrarian_signals
  ORDER BY (abs(contrarian_score)) DESC;


--
-- Name: v_research_seasonality; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_research_seasonality AS
 SELECT ticker,
    name,
    asset_class,
    current_month,
    current_month_bias,
    current_month_historical_return,
    next_month,
    next_month_bias,
    next_month_historical_return,
    updated_at
   FROM consumption.research_seasonality_patterns
  ORDER BY (abs(current_month_historical_return)) DESC;


--
-- Name: v_research_suescores; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_research_suescores AS
 SELECT ticker,
    name,
    report_date,
    eps_estimate,
    eps_actual,
    eps_surprise_pct,
    sue_score,
    sue_decile,
    sue_category,
    drift_signal,
    sector,
    updated_at
   FROM consumption.research_sue_scores
  ORDER BY sue_score DESC;


--
-- Name: earnings_data; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.earnings_data (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    report_date date NOT NULL,
    fiscal_quarter character varying(10),
    actual_eps numeric(10,4),
    estimate_eps numeric(10,4),
    surprise_pct numeric(10,4),
    collected_at timestamp without time zone DEFAULT now()
);


--
-- Name: TABLE earnings_data; Type: COMMENT; Schema: gold; Owner: -
--

COMMENT ON TABLE gold.earnings_data IS 'Raw earnings data for S&P 100 companies. Updated daily.';


--
-- Name: unified_prices; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.unified_prices (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    asset_class character varying(50),
    market character varying(20),
    date date NOT NULL,
    open numeric(20,8),
    high numeric(20,8),
    low numeric(20,8),
    close numeric(20,8),
    volume numeric(20,0),
    adjusted_close numeric(20,8),
    returns_1d numeric(10,6),
    returns_log numeric(10,6),
    primary_source character varying(50),
    all_sources jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: v_s014_earnings_signals; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_s014_earnings_signals AS
 WITH price_sma AS (
         SELECT unified_prices.ticker,
            unified_prices.date,
            unified_prices.close,
            unified_prices.volume,
            unified_prices.open,
            avg(unified_prices.close) OVER (PARTITION BY unified_prices.ticker ORDER BY unified_prices.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS sma_20,
            avg(unified_prices.volume) OVER (PARTITION BY unified_prices.ticker ORDER BY unified_prices.date ROWS BETWEEN 19 PRECEDING AND CURRENT ROW) AS volume_sma_20
           FROM silver.unified_prices
          WHERE ((unified_prices.date >= '2019-01-01'::date) AND (unified_prices.date <= '2024-12-31'::date))
        ), price_changes AS (
         SELECT price_sma.ticker,
            price_sma.date,
            price_sma.close,
            price_sma.volume,
            price_sma.open,
            price_sma.sma_20,
            price_sma.volume_sma_20,
            (price_sma.close - lag(price_sma.close) OVER (PARTITION BY price_sma.ticker ORDER BY price_sma.date)) AS price_change
           FROM price_sma
        ), price_gains AS (
         SELECT price_changes.ticker,
            price_changes.date,
            price_changes.close,
            price_changes.volume,
            price_changes.open,
            price_changes.sma_20,
            price_changes.volume_sma_20,
                CASE
                    WHEN (price_changes.price_change > (0)::numeric) THEN price_changes.price_change
                    ELSE (0)::numeric
                END AS gain,
                CASE
                    WHEN (price_changes.price_change < (0)::numeric) THEN (- price_changes.price_change)
                    ELSE (0)::numeric
                END AS loss
           FROM price_changes
        ), price_rsi AS (
         SELECT price_gains.ticker,
            price_gains.date,
            price_gains.close,
            price_gains.volume,
            price_gains.open,
            price_gains.sma_20,
            price_gains.volume_sma_20,
            avg(price_gains.gain) OVER (PARTITION BY price_gains.ticker ORDER BY price_gains.date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS avg_gain,
            avg(price_gains.loss) OVER (PARTITION BY price_gains.ticker ORDER BY price_gains.date ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS avg_loss
           FROM price_gains
        ), price_indicators AS (
         SELECT price_rsi.ticker,
            price_rsi.date,
            price_rsi.close,
            price_rsi.volume,
            price_rsi.open,
            price_rsi.sma_20,
            price_rsi.volume_sma_20,
                CASE
                    WHEN (price_rsi.avg_loss = (0)::numeric) THEN (100)::numeric
                    ELSE ((100)::numeric - ((100)::numeric / ((1)::numeric + (price_rsi.avg_gain / NULLIF(price_rsi.avg_loss, (0)::numeric)))))
                END AS rsi_14,
            lead(price_rsi.open) OVER (PARTITION BY price_rsi.ticker ORDER BY price_rsi.date) AS next_day_open
           FROM price_rsi
        )
 SELECT e.ticker,
    e.report_date AS earnings_date,
    e.surprise_pct AS eps_surprise_pct,
    pi.rsi_14 AS rsi_14_pre,
    pi.sma_20 AS sma_20_pre,
    pi.close AS close_pre,
    pi.volume AS volume_pre,
    pi.volume_sma_20 AS volume_sma_20_pre,
        CASE
            WHEN ((pi.sma_20 IS NOT NULL) AND (pi.sma_20 > (0)::numeric)) THEN (pi.close / pi.sma_20)
            ELSE NULL::numeric
        END AS price_vs_sma20,
        CASE
            WHEN ((pi.volume_sma_20 IS NOT NULL) AND (pi.volume_sma_20 > (0)::numeric)) THEN (pi.volume / pi.volume_sma_20)
            ELSE NULL::numeric
        END AS volume_vs_sma20,
    pi.next_day_open
   FROM (gold.earnings_data e
     JOIN price_indicators pi ON ((((e.ticker)::text = (pi.ticker)::text) AND (pi.date = ( SELECT max(unified_prices.date) AS max
           FROM silver.unified_prices
          WHERE (((unified_prices.ticker)::text = (e.ticker)::text) AND (unified_prices.date < e.report_date)))))))
  WHERE (((e.report_date >= '2019-01-01'::date) AND (e.report_date <= '2024-12-31'::date)) AND (e.surprise_pct IS NOT NULL))
  ORDER BY e.ticker, e.report_date;


--
-- Name: v_s014_earnings_signals; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_s014_earnings_signals AS
 SELECT ticker,
    earnings_date,
    eps_surprise_pct,
    rsi_14_pre,
    sma_20_pre,
    close_pre,
    volume_pre,
    volume_sma_20_pre,
    price_vs_sma20,
    volume_vs_sma20,
    next_day_open
   FROM gold.v_s014_earnings_signals;


--
-- Name: commodity_futures; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.commodity_futures (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    name character varying(100) NOT NULL,
    category character varying(50) NOT NULL,
    exchange character varying(20) NOT NULL,
    date date NOT NULL,
    open_price numeric(15,4),
    high_price numeric(15,4),
    low_price numeric(15,4),
    close_price numeric(15,4),
    volume bigint,
    returns numeric(10,6),
    log_returns numeric(10,6),
    volatility_20d numeric(10,6),
    sma_50 numeric(15,4),
    sma_200 numeric(15,4),
    month integer,
    quarter integer,
    year integer,
    day_of_year integer,
    collected_at timestamp without time zone DEFAULT now()
);


--
-- Name: TABLE commodity_futures; Type: COMMENT; Schema: gold; Owner: -
--

COMMENT ON TABLE gold.commodity_futures IS 'Historical futures price data for major commodities (20+ years). Updated daily.';


--
-- Name: macro_indicators; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.macro_indicators (
    id integer NOT NULL,
    date date NOT NULL,
    indicator_name character varying(50) NOT NULL,
    value numeric(12,4),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: sector_etfs; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.sector_etfs (
    id integer NOT NULL,
    ticker character varying(10) NOT NULL,
    date date NOT NULL,
    open_price numeric(12,4),
    high_price numeric(12,4),
    low_price numeric(12,4),
    close_price numeric(12,4),
    volume bigint,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: v_s015_sector_rotation; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_s015_sector_rotation AS
 WITH monthly_cpi AS (
         SELECT (date_trunc('month'::text, (macro_indicators.date)::timestamp with time zone))::date AS month,
            macro_indicators.value AS cpi_yoy
           FROM gold.macro_indicators
          WHERE ((macro_indicators.indicator_name)::text = 'CPI_YoY'::text)
        ), monthly_treasury AS (
         SELECT (date_trunc('month'::text, (macro_indicators.date)::timestamp with time zone))::date AS month,
            avg(macro_indicators.value) AS treasury_10y_avg
           FROM gold.macro_indicators
          WHERE ((macro_indicators.indicator_name)::text = 'TREASURY_10Y'::text)
          GROUP BY ((date_trunc('month'::text, (macro_indicators.date)::timestamp with time zone))::date)
        ), monthly_oil AS (
         SELECT (date_trunc('month'::text, (commodity_futures.date)::timestamp with time zone))::date AS month,
            avg(commodity_futures.close_price) AS oil_avg_price
           FROM gold.commodity_futures
          WHERE ((commodity_futures.ticker)::text = 'CL=F'::text)
          GROUP BY ((date_trunc('month'::text, (commodity_futures.date)::timestamp with time zone))::date)
        ), etf_monthly AS (
         SELECT sector_etfs.ticker,
            (date_trunc('month'::text, (sector_etfs.date)::timestamp with time zone))::date AS month,
            min(sector_etfs.date) AS first_date,
            max(sector_etfs.date) AS last_date,
            avg(sector_etfs.close_price) AS avg_close,
            avg(sector_etfs.volume) AS avg_volume
           FROM gold.sector_etfs
          WHERE ((sector_etfs.ticker)::text = ANY ((ARRAY['XLE'::character varying, 'XLP'::character varying, 'XLY'::character varying])::text[]))
          GROUP BY sector_etfs.ticker, (date_trunc('month'::text, (sector_etfs.date)::timestamp with time zone))
        ), etf_prices AS (
         SELECT em.ticker,
            em.month,
            em.first_date,
            em.last_date,
            em.avg_close,
            em.avg_volume,
            se.close_price AS last_close
           FROM (etf_monthly em
             JOIN gold.sector_etfs se ON ((((em.ticker)::text = (se.ticker)::text) AND (em.last_date = se.date))))
        )
 SELECT c.month,
    c.cpi_yoy,
    t.treasury_10y_avg,
    o.oil_avg_price,
    xle.last_close AS xle_close,
    xle.avg_close AS xle_avg,
    xle.avg_volume AS xle_volume,
    xlp.last_close AS xlp_close,
    xlp.avg_close AS xlp_avg,
    xlp.avg_volume AS xlp_volume,
    xly.last_close AS xly_close,
    xly.avg_close AS xly_avg,
    xly.avg_volume AS xly_volume
   FROM (((((monthly_cpi c
     LEFT JOIN monthly_treasury t ON ((c.month = t.month)))
     LEFT JOIN monthly_oil o ON ((c.month = o.month)))
     LEFT JOIN etf_prices xle ON (((c.month = xle.month) AND ((xle.ticker)::text = 'XLE'::text))))
     LEFT JOIN etf_prices xlp ON (((c.month = xlp.month) AND ((xlp.ticker)::text = 'XLP'::text))))
     LEFT JOIN etf_prices xly ON (((c.month = xly.month) AND ((xly.ticker)::text = 'XLY'::text))))
  WHERE ((c.month >= '2019-01-01'::date) AND (c.month <= '2025-12-31'::date))
  ORDER BY c.month;


--
-- Name: v_s015_sector_rotation; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_s015_sector_rotation AS
 SELECT month,
    cpi_yoy,
    treasury_10y_avg,
    oil_avg_price,
    xle_close,
    xle_avg,
    xle_volume,
    xlp_close,
    xlp_avg,
    xlp_volume,
    xly_close,
    xly_avg,
    xly_volume
   FROM gold.v_s015_sector_rotation;


--
-- Name: v_s101_hibor_input; Type: VIEW; Schema: consumption; Owner: -
--

CREATE VIEW consumption.v_s101_hibor_input AS
 SELECT date,
    rate AS hibor_1m_pct,
    lag(rate, 1) OVER (ORDER BY date) AS prev_day_rate,
    (rate - lag(rate, 1) OVER (ORDER BY date)) AS rate_change,
    avg(rate) OVER (ORDER BY date ROWS 20 PRECEDING) AS rate_20d_ma
   FROM gold.interbank_rates
  WHERE (((currency)::text = 'HKD'::text) AND ((tenor)::text = '1M'::text) AND (date >= '2019-01-01'::date))
  ORDER BY date;


--
-- Name: vix_dashboard; Type: TABLE; Schema: consumption; Owner: -
--

CREATE TABLE consumption.vix_dashboard (
    date date NOT NULL,
    vix numeric(12,4),
    vix_sma60 numeric(12,4),
    vix_z60 numeric(12,4),
    regime character varying(20),
    signal_flag integer,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: accruals_quality; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.accruals_quality (
    id integer NOT NULL,
    ticker character varying(10) NOT NULL,
    quarter date NOT NULL,
    net_income numeric(15,2),
    operating_cash_flow numeric(15,2),
    total_assets numeric(15,2),
    accruals numeric(15,2),
    accruals_ratio numeric(8,4),
    quality_score numeric(8,4),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: accruals_quality_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.accruals_quality_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: accruals_quality_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.accruals_quality_id_seq OWNED BY gold.accruals_quality.id;


--
-- Name: agent_events; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.agent_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    event_type character varying(100) NOT NULL,
    strategy_id character varying(50),
    domain character varying(50) DEFAULT 'quant'::character varying,
    agent_name character varying(50) NOT NULL,
    payload_json jsonb DEFAULT '{}'::jsonb,
    status character varying(20) DEFAULT 'pending'::character varying,
    created_at timestamp with time zone DEFAULT now(),
    payload jsonb
);


--
-- Name: asset_registry; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.asset_registry (
    ticker character varying(20) NOT NULL,
    name character varying(100),
    asset_class character varying(20) NOT NULL,
    market character varying(20),
    horizon character varying(20),
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC'::text) + '08:00:00'::interval),
    sector character varying(50),
    description text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: audit_events; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.audit_events (
    id bigint NOT NULL,
    event_time timestamp without time zone DEFAULT now(),
    event_type character varying(100),
    user_id character varying(100),
    source character varying(100),
    action character varying(100),
    details jsonb,
    ip_address inet
);


--
-- Name: audit_events_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.audit_events_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_events_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.audit_events_id_seq OWNED BY gold.audit_events.id;


--
-- Name: commodity_futures_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.commodity_futures_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: commodity_futures_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.commodity_futures_id_seq OWNED BY gold.commodity_futures.id;


--
-- Name: commodity_metrics_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.commodity_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: commodity_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.commodity_metrics_id_seq OWNED BY gold.commodity_metrics.id;


--
-- Name: commodity_seasonality; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.commodity_seasonality (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    name character varying(100) NOT NULL,
    category character varying(50) NOT NULL,
    month integer NOT NULL,
    avg_return numeric(10,6),
    std_return numeric(10,6),
    obs_count integer,
    seasonal_bias character varying(20),
    calculated_at timestamp without time zone DEFAULT now(),
    win_rate numeric,
    z_score numeric
);


--
-- Name: TABLE commodity_seasonality; Type: COMMENT; Schema: gold; Owner: -
--

COMMENT ON TABLE gold.commodity_seasonality IS 'Seasonal patterns calculated from commodities futures data. Updated monthly.';


--
-- Name: commodity_seasonality_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.commodity_seasonality_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: commodity_seasonality_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.commodity_seasonality_id_seq OWNED BY gold.commodity_seasonality.id;


--
-- Name: consensus_ratings; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.consensus_ratings (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    strong_buy integer DEFAULT 0,
    buy integer DEFAULT 0,
    hold integer DEFAULT 0,
    sell integer DEFAULT 0,
    strong_sell integer DEFAULT 0,
    total_analysts integer DEFAULT 0,
    target_high numeric(10,2),
    target_low numeric(10,2),
    target_mean numeric(10,2),
    target_median numeric(10,2),
    current_price numeric(10,2),
    upside_pct numeric(5,2),
    report_date date,
    collected_at timestamp without time zone DEFAULT now()
);


--
-- Name: consensus_ratings_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.consensus_ratings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: consensus_ratings_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.consensus_ratings_id_seq OWNED BY gold.consensus_ratings.id;


--
-- Name: cot_sentiment; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.cot_sentiment (
    instrument character varying(50) NOT NULL,
    date date NOT NULL,
    report_date date NOT NULL,
    noncomm_long bigint,
    noncomm_short bigint,
    net_noncomm bigint,
    cot_z numeric(12,4),
    sentiment character varying(20),
    signal_flag integer DEFAULT 0,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: crypto_funding_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.crypto_funding_metrics (
    symbol character varying(50) NOT NULL,
    date date NOT NULL,
    funding_rate_8h numeric(18,8),
    funding_z numeric(12,4),
    n_obs integer DEFAULT 0,
    signal_flag integer DEFAULT 0,
    regime character varying(20),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: crypto_kpis; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.crypto_kpis (
    id integer NOT NULL,
    ticker text NOT NULL,
    date date NOT NULL,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume numeric,
    body_size numeric,
    upper_shadow numeric,
    lower_shadow numeric,
    candle_type text,
    atr_14 numeric,
    volatility_20d numeric,
    volatility_7d numeric,
    daily_range_pct numeric,
    sma_5 numeric,
    sma_20 numeric,
    sma_50 numeric,
    trend_direction text,
    price_vs_sma20_pct numeric,
    rsi_14 numeric,
    macd_line numeric,
    macd_signal numeric,
    bb_upper numeric,
    bb_lower numeric,
    bb_position numeric,
    volume_sma_20 numeric,
    volume_ratio numeric,
    cond_high_volume boolean,
    cond_rsi_below_30 boolean,
    cond_rsi_above_70 boolean,
    cond_above_bb boolean,
    cond_below_bb boolean,
    crypto_breakout_trigger boolean,
    crypto_oversold_bounce_trigger boolean,
    crypto_volume_spike_trigger boolean,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: crypto_kpis_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.crypto_kpis_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crypto_kpis_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.crypto_kpis_id_seq OWNED BY gold.crypto_kpis.id;


--
-- Name: crypto_metrics_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.crypto_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crypto_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.crypto_metrics_id_seq OWNED BY gold.crypto_metrics.id;


--
-- Name: crypto_technical_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.crypto_technical_metrics (
    id bigint NOT NULL,
    date timestamp without time zone NOT NULL,
    ticker character varying(20) NOT NULL,
    asset_type character varying(20),
    asset_subtype character varying(20),
    sector character varying(50),
    industry character varying(50),
    open_price numeric,
    high_price numeric,
    low_price numeric,
    close_price numeric,
    volume numeric,
    daily_return numeric,
    volatility_20d numeric,
    vwap numeric,
    rsi numeric,
    macd numeric,
    macd_signal numeric,
    atr_14d numeric,
    bollinger_upper numeric,
    bollinger_lower numeric,
    sma_20 numeric,
    sharpe_ratio numeric,
    max_drawdown numeric,
    volume_vs_avg numeric,
    currency character varying(10),
    data_quality_score numeric,
    is_active boolean,
    primary_exchange character varying(20),
    source character varying(20),
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


--
-- Name: crypto_technical_metrics_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.crypto_technical_metrics_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crypto_technical_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.crypto_technical_metrics_id_seq OWNED BY gold.crypto_technical_metrics.id;


--
-- Name: daily_ohlcv; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.daily_ohlcv (
    ticker character varying(50) NOT NULL,
    date date NOT NULL,
    asset_class character varying(50),
    market character varying(20),
    open numeric(18,8),
    high numeric(18,8),
    low numeric(18,8),
    close numeric(18,8),
    volume bigint,
    adjusted_close numeric(18,8),
    returns_1d numeric(12,6),
    primary_source character varying(50),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: delisted_tickers; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.delisted_tickers (
    id bigint NOT NULL,
    ticker character varying(20) NOT NULL,
    name character varying(200),
    sector character varying(100),
    delisted_date date,
    reason character varying(100),
    last_price numeric(18,4),
    successor_ticker character varying(20),
    data_available_from date,
    data_available_to date,
    source character varying(50),
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: delisted_tickers_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.delisted_tickers_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: delisted_tickers_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.delisted_tickers_id_seq OWNED BY gold.delisted_tickers.id;


--
-- Name: earnings_data_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.earnings_data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: earnings_data_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.earnings_data_id_seq OWNED BY gold.earnings_data.id;


--
-- Name: earnings_signals_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.earnings_signals_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: earnings_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.earnings_signals_id_seq OWNED BY gold.earnings_signals.id;


--
-- Name: etf_daily_data; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.etf_daily_data (
    id integer NOT NULL,
    ticker character varying(10) NOT NULL,
    date date NOT NULL,
    open_price numeric(12,4),
    high_price numeric(12,4),
    low_price numeric(12,4),
    close_price numeric(12,4),
    volume bigint,
    dividends numeric(12,4),
    splits numeric(12,4),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: etf_daily_data_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.etf_daily_data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: etf_daily_data_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.etf_daily_data_id_seq OWNED BY gold.etf_daily_data.id;


--
-- Name: fx_alerts; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.fx_alerts (
    id integer NOT NULL,
    "timestamp" timestamp without time zone DEFAULT now(),
    ticker character varying(20),
    alert_type character varying(50),
    severity character varying(20),
    message text,
    value numeric(18,8),
    threshold numeric(18,8),
    acknowledged boolean DEFAULT false
);


--
-- Name: fx_alerts_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.fx_alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fx_alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.fx_alerts_id_seq OWNED BY gold.fx_alerts.id;


--
-- Name: fx_bars_5s; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.fx_bars_5s (
    id bigint NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    ticker character varying(20) NOT NULL,
    open numeric(18,8),
    high numeric(18,8),
    low numeric(18,8),
    close numeric(18,8),
    volume bigint
);


--
-- Name: fx_bars_5s_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.fx_bars_5s_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fx_bars_5s_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.fx_bars_5s_id_seq OWNED BY gold.fx_bars_5s.id;


--
-- Name: fx_metrics_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.fx_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: fx_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.fx_metrics_id_seq OWNED BY gold.fx_metrics.id;


--
-- Name: hft_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.hft_metrics (
    id integer NOT NULL,
    date timestamp without time zone NOT NULL,
    ticker character varying(20) NOT NULL,
    liquidity_pressure double precision,
    fusion_score double precision,
    shock_index double precision,
    arbitrage_gap double precision,
    market_velocity double precision
);


--
-- Name: hft_metrics_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.hft_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: hft_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.hft_metrics_id_seq OWNED BY gold.hft_metrics.id;


--
-- Name: hmm_regime_states; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.hmm_regime_states (
    date date NOT NULL,
    hmm_state smallint,
    hmm_label character varying(10),
    confidence double precision,
    computed_at timestamp without time zone DEFAULT now()
);


--
-- Name: ib_orders; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.ib_orders (
    id integer NOT NULL,
    ibkr_order_id character varying(50),
    strategy_id character varying(50),
    ticker character varying(20),
    action character varying(10),
    order_type character varying(50),
    quantity integer,
    limit_price numeric(18,6),
    stop_price numeric(18,6),
    status character varying(50),
    filled_qty integer,
    avg_fill_price numeric(18,6),
    placed_at timestamp without time zone,
    filled_at timestamp without time zone,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: ib_orders_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.ib_orders_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ib_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.ib_orders_id_seq OWNED BY gold.ib_orders.id;


--
-- Name: ibkr_account_summary; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.ibkr_account_summary (
    account character varying(50) NOT NULL,
    net_liquidation numeric(20,4),
    cash_hkd numeric(20,4),
    cash_usd numeric(20,4),
    available_funds numeric(20,4),
    buying_power numeric(20,4),
    position_count integer,
    fetched_at timestamp without time zone
);


--
-- Name: ibkr_orders; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.ibkr_orders (
    id bigint NOT NULL,
    strategy_id character varying(50),
    ticker character varying(20),
    action character varying(10),
    quantity integer,
    order_type character varying(20),
    order_id character varying(50),
    perm_id character varying(50),
    status character varying(50) DEFAULT 'Submitted'::character varying,
    filled integer DEFAULT 0,
    remaining integer,
    avg_fill_price numeric(20,8),
    last_fill_price numeric(20,8),
    commission numeric(20,8),
    realized_pnl numeric(20,8),
    submit_time timestamp without time zone DEFAULT now(),
    execution_time timestamp without time zone,
    gtc boolean DEFAULT true,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    price numeric(15,4),
    account character varying(50) DEFAULT 'DUP825942'::character varying,
    order_date date DEFAULT CURRENT_DATE
);


--
-- Name: ibkr_orders_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.ibkr_orders_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_orders_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.ibkr_orders_id_seq OWNED BY gold.ibkr_orders.id;


--
-- Name: ibkr_positions_live; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.ibkr_positions_live (
    id bigint NOT NULL,
    account character varying(50) NOT NULL,
    ticker character varying(20) NOT NULL,
    quantity numeric,
    avg_cost numeric,
    market_price numeric,
    market_value numeric,
    unrealized_pnl numeric,
    unrealized_pnl_pct numeric,
    side character varying(10),
    asset_class character varying(20),
    currency character varying(10),
    fetched_at timestamp without time zone
);


--
-- Name: ibkr_positions_live_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.ibkr_positions_live_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: ibkr_positions_live_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.ibkr_positions_live_id_seq OWNED BY gold.ibkr_positions_live.id;


--
-- Name: institutional_holdings; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.institutional_holdings (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    holder_name character varying(100) NOT NULL,
    shares bigint,
    shares_change bigint,
    pct_out numeric(5,2),
    pct_held numeric(5,2),
    value bigint,
    report_date date,
    collected_at timestamp without time zone DEFAULT now()
);


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.institutional_holdings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: institutional_holdings_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.institutional_holdings_id_seq OWNED BY gold.institutional_holdings.id;


--
-- Name: interbank_rates_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.interbank_rates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: interbank_rates_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.interbank_rates_id_seq OWNED BY gold.interbank_rates.id;


--
-- Name: llm_key_entities_config; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.llm_key_entities_config (
    id integer NOT NULL,
    category character varying(50),
    name character varying(100),
    is_active boolean DEFAULT true,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP
);


--
-- Name: key_entities_config_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.key_entities_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: key_entities_config_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.key_entities_config_id_seq OWNED BY gold.llm_key_entities_config.id;


--
-- Name: kpis_metrics; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.kpis_metrics (
    ticker character varying(50) NOT NULL,
    date date NOT NULL,
    close numeric(28,8),
    open numeric(28,8),
    high numeric(28,8),
    low numeric(28,8),
    volume bigint,
    change_1d numeric(8,4),
    change_1w numeric(8,4),
    change_1m numeric(8,4),
    change_3m numeric(8,4),
    change_ytd numeric(8,4),
    body_size numeric(28,8),
    upper_shadow numeric(28,8),
    lower_shadow numeric(28,8),
    candle_type character varying(20),
    gap_up boolean DEFAULT false,
    gap_down boolean DEFAULT false,
    sma_5 numeric(28,8),
    sma_10 numeric(28,8),
    sma_20 numeric(28,8),
    sma_50 numeric(28,8),
    sma_200 numeric(28,8),
    ema_12 numeric(28,8),
    ema_26 numeric(28,8),
    price_vs_sma5_pct numeric(8,4),
    price_vs_sma20_pct numeric(8,4),
    price_vs_sma50_pct numeric(8,4),
    price_vs_sma200_pct numeric(8,4),
    ma_cross_signal character varying(20),
    volume_sma_20 numeric(28,8),
    volume_sma_50 numeric(28,8),
    volume_ratio numeric(8,4),
    relative_volume numeric(8,4),
    atr_14 numeric(28,8),
    atr_14_pct numeric(8,4),
    volatility_20d numeric(8,4),
    volatility_50d numeric(8,4),
    bb_upper numeric(28,8),
    bb_middle numeric(28,8),
    bb_lower numeric(28,8),
    bb_width numeric(8,4),
    bb_position numeric(8,4),
    bb_squeeze boolean DEFAULT false,
    rsi_5 numeric(8,4),
    rsi_9 numeric(8,4),
    rsi_14 numeric(8,4),
    rsi_21 numeric(8,4),
    rsi_trend character varying(20),
    rsi_divergence character varying(20),
    macd_line numeric(18,8),
    macd_signal numeric(18,8),
    macd_histogram numeric(18,8),
    macd_cross character varying(20),
    adx_14 numeric(8,4),
    adx_trend character varying(20),
    plus_di numeric(8,4),
    minus_di numeric(8,4),
    stochastic_k numeric(8,4),
    stochastic_d numeric(8,4),
    stoch_oversold boolean DEFAULT false,
    stoch_overbought boolean DEFAULT false,
    pivot_point numeric(18,8),
    support_1 numeric(18,8),
    support_2 numeric(18,8),
    resistance_1 numeric(18,8),
    resistance_2 numeric(18,8),
    obv numeric(18,8),
    obv_trend character varying(20),
    mfi_14 numeric(8,4),
    pe_ratio numeric(10,4),
    pb_ratio numeric(10,4),
    ps_ratio numeric(10,4),
    ev_ebitda numeric(10,4),
    earnings_surprise numeric(8,4),
    earnings_date date,
    cond_price_up boolean DEFAULT false,
    cond_price_down boolean DEFAULT false,
    cond_gap_up boolean DEFAULT false,
    cond_gap_down boolean DEFAULT false,
    cond_high_volume boolean DEFAULT false,
    cond_low_volume boolean DEFAULT false,
    cond_volume_spike boolean DEFAULT false,
    cond_rsi_oversold boolean DEFAULT false,
    cond_rsi_overbought boolean DEFAULT false,
    cond_rsi_bullish boolean DEFAULT false,
    cond_rsi_bearish boolean DEFAULT false,
    cond_rsi_below_25 boolean DEFAULT false,
    cond_rsi_below_40 boolean DEFAULT false,
    cond_rsi_below_45 boolean DEFAULT false,
    cond_above_sma20 boolean DEFAULT false,
    cond_below_sma20 boolean DEFAULT false,
    cond_above_sma50 boolean DEFAULT false,
    cond_below_sma50 boolean DEFAULT false,
    cond_above_sma200 boolean DEFAULT false,
    cond_below_sma200 boolean DEFAULT false,
    cond_golden_cross boolean DEFAULT false,
    cond_death_cross boolean DEFAULT false,
    cond_above_bb boolean DEFAULT false,
    cond_below_bb boolean DEFAULT false,
    cond_bb_squeeze boolean DEFAULT false,
    cond_macd_bullish boolean DEFAULT false,
    cond_macd_bearish boolean DEFAULT false,
    cond_stoch_oversold boolean DEFAULT false,
    cond_stoch_overbought boolean DEFAULT false,
    cond_strong_trend boolean DEFAULT false,
    cond_bullish_divergence boolean DEFAULT false,
    cond_bearish_divergence boolean DEFAULT false,
    s001_high_vol_pullback boolean DEFAULT false,
    s002_oversold_bounce boolean DEFAULT false,
    s003_rsi_divergence boolean DEFAULT false,
    s009_extreme_rsi_vol boolean DEFAULT false,
    breakout_sma20 boolean DEFAULT false,
    breakdown_sma20 boolean DEFAULT false,
    mean_reversion boolean DEFAULT false,
    momentum_buy boolean DEFAULT false,
    momentum_sell boolean DEFAULT false,
    updated_at timestamp without time zone DEFAULT now(),
    data_quality_score integer DEFAULT 100,
    s007_3day_monday boolean DEFAULT false,
    s012_tech_momentum boolean DEFAULT false,
    stoch_k numeric,
    stoch_d numeric,
    adx numeric,
    adx_plus_di numeric,
    adx_minus_di numeric,
    vwap numeric,
    vol_sma_20 numeric,
    vol_ratio numeric
);


--
-- Name: macro_event_flags; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.macro_event_flags (
    date date NOT NULL,
    cpi_flag integer DEFAULT 0,
    nfp_flag integer DEFAULT 0,
    fed_funds_flag integer DEFAULT 0,
    event_flag integer DEFAULT 0,
    event_count integer DEFAULT 0,
    severity character varying(20),
    updated_at timestamp with time zone DEFAULT now(),
    eia_flag smallint DEFAULT 0
);


--
-- Name: macro_indicators_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.macro_indicators_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: macro_indicators_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.macro_indicators_id_seq OWNED BY gold.macro_indicators.id;


--
-- Name: market_regimes; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.market_regimes (
    id integer NOT NULL,
    "timestamp" timestamp without time zone DEFAULT ((CURRENT_TIMESTAMP AT TIME ZONE 'UTC'::text) + '08:00:00'::interval),
    region character varying(20),
    regime_name character varying(20),
    volatility_index double precision,
    dominance_sector character varying(50)
);


--
-- Name: market_regimes_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.market_regimes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: market_regimes_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.market_regimes_id_seq OWNED BY gold.market_regimes.id;


--
-- Name: market_sentiment_daily; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.market_sentiment_daily (
    id integer NOT NULL,
    market character varying(10) NOT NULL,
    date date NOT NULL,
    rating character varying(20) NOT NULL,
    score numeric(5,2),
    bull_percentage numeric(5,2),
    bear_percentage numeric(5,2),
    index_change_score numeric(5,2),
    breadth_score numeric(5,2),
    technical_score numeric(5,2),
    vix_score numeric(5,2),
    index_change_pct numeric(8,4),
    advancing_pct numeric(5,2),
    above_ma50_pct numeric(5,2),
    rsi_avg numeric(5,2),
    vix_level numeric(8,4),
    description text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: market_sentiment_daily_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.market_sentiment_daily_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: market_sentiment_daily_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.market_sentiment_daily_id_seq OWNED BY gold.market_sentiment_daily.id;


--
-- Name: metric_definitions; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.metric_definitions (
    id integer NOT NULL,
    asset_class character varying(20),
    metric_name character varying(50),
    formula_raw text,
    description text,
    weight_impact character varying(20),
    source character varying(50)
);


--
-- Name: metric_definitions_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.metric_definitions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: metric_definitions_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.metric_definitions_id_seq OWNED BY gold.metric_definitions.id;


--
-- Name: nfp_equity_drift_backtests; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.nfp_equity_drift_backtests (
    id integer NOT NULL,
    strategy_name character varying(64) NOT NULL,
    version character varying(8) NOT NULL,
    backtest_date date NOT NULL,
    in_sample_sharpe numeric,
    oos_sharpe numeric,
    win_rate numeric,
    total_return numeric,
    n_trades integer,
    artifact_path text,
    created_at timestamp with time zone DEFAULT now()
);


--
-- Name: nfp_equity_drift_backtests_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.nfp_equity_drift_backtests_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: nfp_equity_drift_backtests_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.nfp_equity_drift_backtests_id_seq OWNED BY gold.nfp_equity_drift_backtests.id;


--
-- Name: paper_run_log; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.paper_run_log (
    id integer NOT NULL,
    run_date date NOT NULL,
    run_type text,
    signals_eval integer,
    orders_placed integer,
    orders_skipped integer,
    gate_reasons text,
    total_pnl numeric,
    drawdown_pct numeric,
    duration_ms integer,
    status text,
    created_at timestamp with time zone DEFAULT now(),
    daily_pnl numeric(18,6),
    cumulative_pnl numeric(18,6),
    num_positions integer,
    position_pnls jsonb,
    weekly_review jsonb,
    CONSTRAINT paper_run_log_run_type_check CHECK ((run_type = ANY (ARRAY['morning'::text, 'eod'::text, 'weekly_review'::text]))),
    CONSTRAINT paper_run_log_status_check CHECK ((status = ANY (ARRAY['ok'::text, 'skipped'::text, 'halted'::text, 'error'::text])))
);


--
-- Name: paper_run_log_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.paper_run_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: paper_run_log_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.paper_run_log_id_seq OWNED BY gold.paper_run_log.id;


--
-- Name: paper_strategies; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.paper_strategies (
    id integer NOT NULL,
    strategy_id text NOT NULL,
    strategy_name text,
    description text,
    asset_class text,
    status text DEFAULT 'active'::text,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: paper_strategies_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.paper_strategies_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: paper_strategies_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.paper_strategies_id_seq OWNED BY gold.paper_strategies.id;


--
-- Name: paper_trades; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.paper_trades (
    id integer NOT NULL,
    ts timestamp with time zone DEFAULT now() NOT NULL,
    strategy_id text NOT NULL,
    instrument text NOT NULL,
    direction text,
    size numeric,
    entry_price numeric,
    exit_price numeric,
    pnl numeric,
    regime text,
    signal_value numeric,
    ic_at_entry numeric,
    confidence_at_entry numeric,
    status text,
    rehearsal boolean DEFAULT false,
    updated_at timestamp with time zone DEFAULT now(),
    ticker text,
    n_shares integer,
    CONSTRAINT paper_trades_direction_check CHECK ((direction = ANY (ARRAY['long'::text, 'short'::text, 'flat'::text]))),
    CONSTRAINT paper_trades_status_check CHECK ((status = ANY (ARRAY['open'::text, 'closed'::text, 'cancelled'::text])))
);


--
-- Name: paper_trades_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.paper_trades_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: paper_trades_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.paper_trades_id_seq OWNED BY gold.paper_trades.id;


--
-- Name: platform_settings; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.platform_settings (
    key character varying(100) NOT NULL,
    value text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: portfolio_snapshots; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.portfolio_snapshots (
    id bigint NOT NULL,
    snapshot_date date NOT NULL,
    portfolio_type character varying(20) NOT NULL,
    total_value numeric(18,8),
    cash_value numeric(18,8),
    positions_value numeric(18,8),
    daily_pnl numeric(18,8),
    daily_pnl_pct numeric(10,4),
    mtd_pnl numeric(18,8),
    ytd_pnl numeric(18,8),
    total_pnl numeric(18,8),
    gross_exposure numeric(10,4),
    net_exposure numeric(10,4),
    beta_adjusted_exposure numeric(10,4),
    var_95 numeric(18,8),
    calculated_at timestamp without time zone DEFAULT now()
);


--
-- Name: portfolio_snapshots_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.portfolio_snapshots_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: portfolio_snapshots_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.portfolio_snapshots_id_seq OWNED BY gold.portfolio_snapshots.id;


--
-- Name: positions; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.positions (
    id integer NOT NULL,
    strategy_id character varying(50),
    ticker character varying(20),
    side character varying(10),
    quantity numeric(18,6),
    entry_price numeric(18,6),
    current_price numeric(18,6),
    market_value numeric(18,2),
    unrealized_pnl numeric(18,2),
    realized_pnl numeric(18,2),
    status character varying(20),
    opened_at timestamp without time zone,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: positions_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.positions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: positions_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.positions_id_seq OWNED BY gold.positions.id;


--
-- Name: regime_features; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.regime_features (
    date date NOT NULL,
    adx14 double precision,
    hurst_30 double precision,
    rv5d double precision,
    rv_iv_ratio double precision,
    vix_z60 double precision,
    spy_above_200 smallint,
    breadth_50 double precision,
    funding_z double precision,
    event_flag smallint,
    computed_at timestamp without time zone DEFAULT now(),
    adx_hurst_cross double precision,
    rv5d_change double precision
);


--
-- Name: regime_label; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.regime_label (
    date date NOT NULL,
    regime character varying(10),
    hmm_label character varying(10),
    override_used boolean,
    confidence double precision,
    computed_at timestamp without time zone DEFAULT now(),
    severity integer DEFAULT 0
);


--
-- Name: s9_macd_signals; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.s9_macd_signals (
    id integer NOT NULL,
    strategy_id character varying(50) DEFAULT 'S9_MACD_Momentum_V2'::character varying NOT NULL,
    ticker character varying(20) NOT NULL,
    signal_date date NOT NULL,
    entry_date date NOT NULL,
    macd_hist numeric,
    prev_macd_hist numeric,
    volume_ratio numeric,
    signal_strength numeric,
    entry_price_est numeric,
    is_active boolean DEFAULT true,
    processed_at timestamp without time zone DEFAULT now(),
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: s9_macd_signals_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.s9_macd_signals_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: s9_macd_signals_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.s9_macd_signals_id_seq OWNED BY gold.s9_macd_signals.id;


--
-- Name: s9_paper_trades; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.s9_paper_trades (
    id integer NOT NULL,
    strategy_id character varying(50) DEFAULT 'S9_MACD_Momentum_V2'::character varying NOT NULL,
    ticker character varying(20) NOT NULL,
    entry_date date NOT NULL,
    exit_date date,
    direction character varying(10) DEFAULT 'LONG'::character varying,
    entry_price numeric,
    exit_price numeric,
    pnl_pct numeric,
    hold_days integer,
    exit_reason character varying(50),
    signal_id integer,
    execution_mode character varying(20) DEFAULT 'PAPER'::character varying,
    status character varying(20) DEFAULT 'OPEN'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: s9_paper_trades_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.s9_paper_trades_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: s9_paper_trades_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.s9_paper_trades_id_seq OWNED BY gold.s9_paper_trades.id;


--
-- Name: seasonality_patterns; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.seasonality_patterns (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    asset_class character varying(20) NOT NULL,
    month integer NOT NULL,
    avg_return_pct numeric(10,4),
    win_rate numeric(5,4),
    std_dev numeric(10,4),
    max_gain_pct numeric(10,4),
    max_loss_pct numeric(10,4),
    sample_size integer,
    seasonal_bias character varying(20),
    z_score numeric(8,4),
    lookback_years integer DEFAULT 20,
    calculated_at timestamp without time zone DEFAULT now()
);


--
-- Name: seasonality_patterns_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.seasonality_patterns_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: seasonality_patterns_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.seasonality_patterns_id_seq OWNED BY gold.seasonality_patterns.id;


--
-- Name: sector_etfs_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.sector_etfs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sector_etfs_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.sector_etfs_id_seq OWNED BY gold.sector_etfs.id;


--
-- Name: sentiment_mart; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.sentiment_mart (
    date timestamp without time zone NOT NULL,
    id integer NOT NULL,
    perspective character varying(50),
    entity_name character varying(100),
    sentiment_score double precision,
    bullish_reasons text[],
    bearish_reasons text[],
    impact_level character varying(20),
    swarm_summary text
);


--
-- Name: sentiment_mart_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.sentiment_mart_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sentiment_mart_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.sentiment_mart_id_seq OWNED BY gold.sentiment_mart.id;


--
-- Name: signal_cancellations; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.signal_cancellations (
    id integer NOT NULL,
    strategy_id character varying(100) NOT NULL,
    ticker character varying(20) NOT NULL,
    cancellation_time timestamp without time zone NOT NULL,
    reason text NOT NULL,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: signal_cancellations_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.signal_cancellations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: signal_cancellations_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.signal_cancellations_id_seq OWNED BY gold.signal_cancellations.id;


--
-- Name: stock_metrics_history; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.stock_metrics_history (
    date date NOT NULL,
    ticker character varying(20) NOT NULL,
    sector character varying(100),
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume bigint,
    vwap numeric,
    rsi_14 double precision,
    macd_line numeric,
    macd_signal numeric,
    macd_hist double precision,
    sma_50 double precision,
    sma_200 double precision,
    stoch_k numeric,
    stoch_d numeric,
    adx numeric,
    adx_plus_di numeric,
    adx_minus_di numeric,
    psar numeric,
    psar_direction character varying(10),
    atr_14 double precision,
    beta double precision,
    implied_volatility double precision,
    sharpe_ratio double precision,
    relative_vol_10d double precision,
    rel_strength_sp500 double precision,
    rel_strength_sector double precision,
    dist_from_52w_high double precision,
    dist_from_ytd_high double precision,
    dist_from_ytd_low double precision,
    pe_ratio_ttm double precision,
    ps_ratio double precision,
    eps_growth_qbq double precision,
    debt_to_equity double precision,
    free_cash_flow double precision,
    prophet_forecast double precision,
    candlestick_pattern character varying(50),
    candlestick_sentiment double precision,
    hit_rate_1d double precision,
    hit_rate_7d double precision,
    returns_1d double precision,
    returns_5d double precision,
    returns_21d double precision,
    volatility_21d double precision,
    volume_sma_20 double precision,
    volume_ratio double precision,
    golden_cross boolean,
    death_cross boolean,
    above_sma_200 boolean,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: stock_metrics; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.stock_metrics AS
 SELECT date,
    ticker,
    sector,
    open,
    high,
    low,
    close,
    volume,
    vwap,
    rsi_14,
    macd_hist,
    sma_50,
    sma_200,
    atr_14,
    beta,
    sharpe_ratio,
    rel_strength_sp500,
    rel_strength_sector,
    dist_from_52w_high,
    implied_volatility,
    candlestick_pattern,
    candlestick_sentiment,
    golden_cross,
    death_cross,
    above_sma_200,
    created_at
   FROM gold.stock_metrics_history
  WHERE (date >= ( SELECT (max(stock_metrics_history_1.date) - '5 days'::interval)
           FROM gold.stock_metrics_history stock_metrics_history_1));


--
-- Name: stock_metrics_new; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.stock_metrics_new (
    ticker character varying NOT NULL,
    date date NOT NULL,
    sector character varying,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume bigint,
    vwap numeric,
    returns_1d double precision,
    returns_5d double precision,
    returns_21d double precision,
    change_1d numeric,
    change_1w numeric,
    change_1m numeric,
    change_3m numeric,
    change_ytd numeric,
    rsi_14 double precision,
    macd_line numeric,
    macd_signal numeric,
    macd_hist double precision,
    sma_50 double precision,
    sma_200 double precision,
    stoch_k numeric,
    stoch_d numeric,
    adx numeric,
    adx_plus_di numeric,
    adx_minus_di numeric,
    psar numeric,
    psar_direction character varying,
    atr_14 double precision,
    volatility_21d double precision,
    volume_sma_20 double precision,
    volume_ratio double precision,
    sma_5 numeric,
    sma_10 numeric,
    sma_20 numeric,
    ema_12 numeric,
    ema_26 numeric,
    price_vs_sma5_pct numeric,
    price_vs_sma20_pct numeric,
    price_vs_sma50_pct numeric,
    price_vs_sma200_pct numeric,
    ma_cross_signal character varying,
    volume_sma_50 numeric,
    relative_volume numeric,
    atr_14_pct numeric,
    volatility_20d numeric,
    volatility_50d numeric,
    bb_upper numeric,
    bb_middle numeric,
    bb_lower numeric,
    bb_width numeric,
    bb_position numeric,
    bb_squeeze boolean,
    rsi_5 numeric,
    rsi_9 numeric,
    rsi_21 numeric,
    rsi_trend character varying,
    rsi_divergence character varying,
    macd_cross character varying,
    stochastic_k numeric,
    stochastic_d numeric,
    stoch_oversold boolean,
    stoch_overbought boolean,
    adx_trend character varying,
    plus_di numeric,
    minus_di numeric,
    pivot_point numeric,
    support_1 numeric,
    support_2 numeric,
    resistance_1 numeric,
    resistance_2 numeric,
    obv numeric,
    obv_trend character varying,
    mfi_14 numeric,
    beta double precision,
    implied_volatility double precision,
    sharpe_ratio double precision,
    relative_vol_10d double precision,
    rel_strength_sp500 double precision,
    rel_strength_sector double precision,
    dist_from_52w_high double precision,
    dist_from_ytd_high double precision,
    dist_from_ytd_low double precision,
    pe_ratio_ttm double precision,
    ps_ratio double precision,
    eps_growth_qbq double precision,
    debt_to_equity double precision,
    free_cash_flow double precision,
    prophet_forecast double precision,
    pe_ratio numeric,
    pb_ratio numeric,
    ev_ebitda numeric,
    earnings_surprise numeric,
    earnings_date date,
    body_size numeric,
    upper_shadow numeric,
    lower_shadow numeric,
    candle_type character varying,
    gap_up boolean,
    gap_down boolean,
    candlestick_pattern character varying,
    candlestick_sentiment double precision,
    golden_cross boolean,
    death_cross boolean,
    above_sma_200 boolean,
    breakout_sma20 boolean,
    breakdown_sma20 boolean,
    mean_reversion boolean,
    momentum_buy boolean,
    momentum_sell boolean,
    cond_price_up boolean,
    cond_price_down boolean,
    cond_gap_up boolean,
    cond_gap_down boolean,
    cond_high_volume boolean,
    cond_low_volume boolean,
    cond_volume_spike boolean,
    cond_rsi_oversold boolean,
    cond_rsi_overbought boolean,
    cond_rsi_bullish boolean,
    cond_rsi_bearish boolean,
    cond_rsi_below_25 boolean,
    cond_rsi_below_40 boolean,
    cond_rsi_below_45 boolean,
    cond_above_sma20 boolean,
    cond_below_sma20 boolean,
    cond_above_sma50 boolean,
    cond_below_sma50 boolean,
    cond_above_sma200 boolean,
    cond_below_sma200 boolean,
    cond_golden_cross boolean,
    cond_death_cross boolean,
    cond_above_bb boolean,
    cond_below_bb boolean,
    cond_bb_squeeze boolean,
    cond_macd_bullish boolean,
    cond_macd_bearish boolean,
    cond_stoch_oversold boolean,
    cond_stoch_overbought boolean,
    cond_strong_trend boolean,
    cond_bullish_divergence boolean,
    cond_bearish_divergence boolean,
    s001_high_vol_pullback boolean,
    s002_oversold_bounce boolean,
    s003_rsi_divergence boolean,
    s007_3day_monday boolean,
    s009_extreme_rsi_vol boolean,
    s012_tech_momentum boolean,
    hit_rate_1d double precision,
    hit_rate_7d double precision,
    data_quality_score integer,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: strategy_backtest_runs; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_backtest_runs (
    run_id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_id character varying(50) NOT NULL,
    run_number integer NOT NULL,
    run_by character varying(50) DEFAULT 'research-agent'::character varying,
    is_start date NOT NULL,
    is_end date NOT NULL,
    oos_start date NOT NULL,
    oos_end date NOT NULL,
    sharpe_is numeric(8,4),
    returns_is numeric(8,4),
    max_drawdown_is numeric(8,4),
    trade_count_is integer,
    win_rate_is numeric(6,4),
    turnover_is numeric(8,4),
    sharpe_oos numeric(8,4),
    returns_oos numeric(8,4),
    max_drawdown_oos numeric(8,4),
    trade_count_oos integer,
    win_rate_oos numeric(6,4),
    turnover_oos numeric(8,4),
    cvar_95_oos numeric(8,4),
    max_single_asset_exposure numeric(6,4),
    passed_max_drawdown boolean GENERATED ALWAYS AS ((max_drawdown_oos > '-0.20'::numeric)) STORED,
    passed_sharpe_oos boolean GENERATED ALWAYS AS ((sharpe_oos > 0.50)) STORED,
    passed_trade_count boolean GENERATED ALWAYS AS ((trade_count_oos > 30)) STORED,
    passed_turnover boolean GENERATED ALWAYS AS ((turnover_oos < 2.0)) STORED,
    passed_cvar boolean GENERATED ALWAYS AS ((cvar_95_oos > '-0.10'::numeric)) STORED,
    all_risk_gates_passed boolean,
    parameters_used jsonb DEFAULT '{}'::jsonb,
    notes text,
    created_at timestamp without time zone DEFAULT now(),
    annual_pnl_2024 numeric,
    annual_pnl_2025 numeric,
    annual_pnl_2026 numeric,
    bull_sharpe numeric,
    bear_sharpe numeric,
    bull_n integer,
    bear_n integer
);


--
-- Name: strategy_backtest_trades; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_backtest_trades (
    trade_id uuid DEFAULT gen_random_uuid() NOT NULL,
    run_id uuid NOT NULL,
    strategy_id character varying(50) NOT NULL,
    ticker character varying(20) NOT NULL,
    period character varying(5) NOT NULL,
    entry_date date NOT NULL,
    exit_date date,
    entry_price numeric(18,6) NOT NULL,
    exit_price numeric(18,6),
    pnl_pct numeric(10,4),
    holding_days integer,
    exit_reason character varying(50),
    signal_score numeric(6,4),
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT strategy_backtest_trades_period_check CHECK (((period)::text = ANY ((ARRAY['IS'::character varying, 'OOS'::character varying])::text[])))
);


--
-- Name: strategy_backtests; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_backtests (
    strategy_id smallint NOT NULL,
    run_date date NOT NULL,
    sharpe double precision,
    calmar double precision,
    max_dd double precision,
    win_rate double precision,
    n_trades integer,
    period_start date,
    period_end date
);


--
-- Name: strategy_configs; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_configs (
    id integer NOT NULL,
    strategy_id character varying(50),
    config_key character varying(100) NOT NULL,
    config_value jsonb,
    description text,
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: strategy_configs_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_configs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_configs_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_configs_id_seq OWNED BY gold.strategy_configs.id;


--
-- Name: strategy_definitions; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_definitions (
    id integer NOT NULL,
    strategy_id text NOT NULL,
    strategy_name text,
    strategy_type text,
    description text,
    parameters jsonb,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    execution_mode text DEFAULT 'PAPER_TRADING'::text,
    status text DEFAULT 'active'::text
);


--
-- Name: strategy_definitions_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_definitions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_definitions_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_definitions_id_seq OWNED BY gold.strategy_definitions.id;


--
-- Name: strategy_performance_log; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_performance_log (
    id integer NOT NULL,
    strategy_id character varying(50) NOT NULL,
    log_date date NOT NULL,
    daily_pnl numeric(18,4),
    daily_pnl_pct numeric(8,4),
    cumulative_pnl numeric(18,4),
    open_positions integer,
    signals_fired integer,
    in_market_capital numeric(18,2),
    notes text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: strategy_performance_log_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_performance_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_performance_log_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_performance_log_id_seq OWNED BY gold.strategy_performance_log.id;


--
-- Name: strategy_qa_reviews; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_qa_reviews (
    review_id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_id character varying(50) NOT NULL,
    run_id uuid,
    reviewed_by character varying(50) DEFAULT 'qa-agent'::character varying,
    decision character varying(20) NOT NULL,
    conviction_score numeric(4,2),
    sharpe_stability numeric(4,2),
    trade_count_score numeric(4,2),
    drawdown_score numeric(4,2),
    regime_score numeric(4,2),
    failed_gates text[],
    passed_gates text[],
    warnings text[],
    full_comment text,
    reviewed_at timestamp without time zone DEFAULT now(),
    CONSTRAINT strategy_qa_reviews_decision_check CHECK (((decision)::text = ANY ((ARRAY['APPROVED'::character varying, 'REJECTED'::character varying])::text[])))
);


--
-- Name: strategy_registry; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_registry (
    strategy_id character varying(50) NOT NULL,
    name character varying(200) NOT NULL,
    asset_class character varying(20) NOT NULL,
    universe_tickers text[] NOT NULL,
    frequency character varying(20) DEFAULT 'daily'::character varying,
    execution_mode character varying(20) DEFAULT 'SIMULATION'::character varying,
    status character varying(20) DEFAULT 'paper'::character varying,
    sharpe_oos numeric(8,4),
    max_drawdown_oos numeric(8,4),
    trade_count_oos integer,
    win_rate_oos numeric(6,4),
    conviction_score numeric(4,2),
    assigned_capital numeric(18,2) DEFAULT 10000,
    in_market_capital numeric(18,2) DEFAULT 0,
    approved_by character varying(50),
    approved_at timestamp without time zone,
    deployed_at timestamp without time zone,
    last_signal_at timestamp without time zone,
    retired_at timestamp without time zone,
    retirement_reason text,
    signal_logic text,
    exit_logic text,
    signal_file_path text,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT strategy_registry_execution_mode_check CHECK (((execution_mode)::text = ANY ((ARRAY['SIMULATION'::character varying, 'LIVE'::character varying])::text[]))),
    CONSTRAINT strategy_registry_status_check CHECK (((status)::text = ANY ((ARRAY['paper'::character varying, 'live'::character varying, 'paused'::character varying, 'retired'::character varying])::text[])))
);


--
-- Name: COLUMN strategy_registry.status; Type: COMMENT; Schema: gold; Owner: -
--

COMMENT ON COLUMN gold.strategy_registry.status IS 'Allowed values (CHECK constraint): paper, live, paused, retired. Use paused for strategies in backtesting/research phase. Use paper for approved live paper trading. Use rejected/retired for archived strategies.';


--
-- Name: strategy_research; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_research (
    strategy_id character varying(50) NOT NULL,
    name character varying(200) NOT NULL,
    thesis text,
    asset_class character varying(20) NOT NULL,
    universe_tickers text[] NOT NULL,
    entry_logic text,
    exit_logic text,
    position_sizing jsonb DEFAULT '{}'::jsonb,
    frequency character varying(20) DEFAULT 'daily'::character varying,
    generation integer DEFAULT 1,
    parent_strategy_id character varying(50),
    source character varying(50) DEFAULT 'research-agent'::character varying,
    status character varying(30) DEFAULT 'pending'::character varying,
    rejection_reason text,
    rejection_flags text[],
    kanban_task_id character varying(100),
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT strategy_research_status_check CHECK (((status)::text = ANY ((ARRAY['pending'::character varying, 'backtesting'::character varying, 'risk_review'::character varying, 'qa_review'::character varying, 'approved'::character varying, 'deployed'::character varying, 'rejected'::character varying, 'retired'::character varying])::text[])))
);


--
-- Name: strategy_risk_reviews; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_risk_reviews (
    review_id uuid DEFAULT gen_random_uuid() NOT NULL,
    strategy_id character varying(50) NOT NULL,
    run_id uuid,
    reviewed_by character varying(50) DEFAULT 'risk-agent'::character varying,
    decision character varying(20) NOT NULL,
    risk_score numeric(4,2),
    failed_gates text[],
    passed_gates text[],
    suggested_fixes text,
    full_comment text,
    reviewed_at timestamp without time zone DEFAULT now(),
    CONSTRAINT strategy_risk_reviews_decision_check CHECK (((decision)::text = ANY ((ARRAY['APPROVED'::character varying, 'REJECTED'::character varying])::text[])))
);


--
-- Name: strategy_signal_criteria; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_signal_criteria (
    id integer NOT NULL,
    strategy_id character varying(50) NOT NULL,
    signal_type character varying(10) NOT NULL,
    criterion_name character varying(50) NOT NULL,
    operator character varying(5) NOT NULL,
    threshold numeric NOT NULL,
    logic_mode character varying(10) NOT NULL,
    logic_threshold integer,
    created_at timestamp without time zone DEFAULT now(),
    CONSTRAINT strategy_signal_criteria_logic_mode_check CHECK (((logic_mode)::text = ANY ((ARRAY['all'::character varying, 'any'::character varying])::text[]))),
    CONSTRAINT strategy_signal_criteria_operator_check CHECK (((operator)::text = ANY ((ARRAY['>'::character varying, '<'::character varying, '>='::character varying, '<='::character varying, '='::character varying, '!='::character varying])::text[]))),
    CONSTRAINT strategy_signal_criteria_signal_type_check CHECK (((signal_type)::text = ANY ((ARRAY['buy'::character varying, 'sell'::character varying])::text[])))
);


--
-- Name: strategy_signal_criteria_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_signal_criteria_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_signal_criteria_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_signal_criteria_id_seq OWNED BY gold.strategy_signal_criteria.id;


--
-- Name: strategy_signals; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_signals (
    date date NOT NULL,
    strategy_id smallint NOT NULL,
    strategy_name character varying(50),
    signal smallint,
    position_size double precision,
    regime character varying(10),
    confidence double precision,
    active boolean,
    computed_at timestamp without time zone DEFAULT now()
);


--
-- Name: strategy_templates; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_templates (
    id integer NOT NULL,
    template_id character varying(50) NOT NULL,
    name character varying(200),
    description text,
    asset_class character varying(50),
    category character varying(50),
    default_params jsonb,
    required_data jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: strategy_templates_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_templates_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_templates_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_templates_id_seq OWNED BY gold.strategy_templates.id;


--
-- Name: strategy_thresholds; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_thresholds (
    id integer NOT NULL,
    strategy_id character varying(50),
    metric_name character varying(100) NOT NULL,
    min_value numeric(18,6),
    max_value numeric(18,6),
    trigger_action character varying(50),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: strategy_thresholds_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_thresholds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_thresholds_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_thresholds_id_seq OWNED BY gold.strategy_thresholds.id;


--
-- Name: strategy_ticker_scores; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_ticker_scores (
    id integer NOT NULL,
    strategy_id character varying(50) NOT NULL,
    ticker character varying(20) NOT NULL,
    score numeric(5,2),
    signal_action character varying(10),
    entry_score numeric(5,2),
    exit_score numeric(5,2),
    criteria_met jsonb DEFAULT '{}'::jsonb,
    position_status character varying(20) DEFAULT 'NONE'::character varying,
    deployed_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    CONSTRAINT strategy_ticker_scores_score_check CHECK (((score >= (0)::numeric) AND (score <= (100)::numeric))),
    CONSTRAINT strategy_ticker_scores_signal_action_check CHECK (((signal_action)::text = ANY ((ARRAY['BUY'::character varying, 'SELL'::character varying, 'HOLD'::character varying])::text[])))
);


--
-- Name: strategy_ticker_scores_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_ticker_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_ticker_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_ticker_scores_id_seq OWNED BY gold.strategy_ticker_scores.id;


--
-- Name: strategy_universes; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.strategy_universes (
    id integer NOT NULL,
    strategy_id character varying(50) NOT NULL,
    ticker character varying(20) NOT NULL,
    is_active boolean DEFAULT true,
    added_at timestamp without time zone DEFAULT now(),
    removed_at timestamp without time zone
);


--
-- Name: strategy_universes_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.strategy_universes_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: strategy_universes_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.strategy_universes_id_seq OWNED BY gold.strategy_universes.id;


--
-- Name: sue_scores; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.sue_scores (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    report_date date NOT NULL,
    fiscal_quarter character varying(10),
    actual_eps numeric(10,4),
    estimate_eps numeric(10,4),
    surprise_pct numeric(10,4),
    eps_change numeric(10,4),
    expected_eps numeric(10,4),
    sue numeric(10,4),
    sue_decile integer,
    sue_category character varying(20),
    calculated_at timestamp without time zone DEFAULT now()
);


--
-- Name: TABLE sue_scores; Type: COMMENT; Schema: gold; Owner: -
--

COMMENT ON TABLE gold.sue_scores IS 'SUE (Standardized Unexpected Earnings) scores calculated from earnings data. SUE = (Actual - Expected) / StdDev';


--
-- Name: sue_scores_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.sue_scores_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sue_scores_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.sue_scores_id_seq OWNED BY gold.sue_scores.id;


--
-- Name: sync_schedules; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.sync_schedules (
    id integer NOT NULL,
    component character varying(50),
    frequency character varying(20) DEFAULT '1hr'::character varying,
    last_run timestamp without time zone,
    is_active boolean DEFAULT true,
    schedule_cron character varying(50),
    status character varying(20) DEFAULT 'active'::character varying
);


--
-- Name: sync_schedules_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.sync_schedules_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: sync_schedules_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.sync_schedules_id_seq OWNED BY gold.sync_schedules.id;


--
-- Name: system_config; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.system_config (
    id integer NOT NULL,
    component character varying(50) NOT NULL,
    key character varying(100) NOT NULL,
    value text,
    value_type character varying(20),
    description text,
    is_active boolean DEFAULT true,
    updated_by character varying(100),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: system_config_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.system_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: system_config_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.system_config_id_seq OWNED BY gold.system_config.id;


--
-- Name: trade_executions; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.trade_executions (
    id integer NOT NULL,
    strategy_id character varying(100),
    ticker character varying(20),
    execution_mode character varying(20),
    order_type character varying(20),
    side character varying(10),
    quantity integer,
    price numeric,
    ibkr_order_id character varying(50),
    status character varying(50),
    executed_at timestamp without time zone DEFAULT now(),
    entry_price numeric(20,8),
    exit_price numeric(20,8),
    pnl numeric(20,8),
    pnl_pct numeric(10,4)
);


--
-- Name: trade_executions_id_seq; Type: SEQUENCE; Schema: gold; Owner: -
--

CREATE SEQUENCE gold.trade_executions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: trade_executions_id_seq; Type: SEQUENCE OWNED BY; Schema: gold; Owner: -
--

ALTER SEQUENCE gold.trade_executions_id_seq OWNED BY gold.trade_executions.id;


--
-- Name: v_agent_activity_feed; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_agent_activity_feed AS
 SELECT agent_name,
    event_type,
    payload_json AS payload,
    (payload_json ->> 'detail'::text) AS detail,
    (payload_json ->> 'strategy_id'::text) AS strategy_id,
    (payload_json ->> 'instrument'::text) AS instrument,
    created_at AS ts
   FROM gold.agent_events
  ORDER BY created_at DESC
 LIMIT 50;


--
-- Name: v_agent_completed_work; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_agent_completed_work AS
 SELECT 'qa_review'::text AS work_type,
    sqr.strategy_id,
    sqr.reviewed_by AS processed_by,
    sqr.decision AS processing_status,
    sqr.conviction_score,
    sqr.reviewed_at AS processed_at
   FROM gold.strategy_qa_reviews sqr
UNION ALL
 SELECT 'risk_review'::text AS work_type,
    srr.strategy_id,
    srr.reviewed_by AS processed_by,
    srr.decision AS processing_status,
    srr.risk_score AS conviction_score,
    srr.reviewed_at AS processed_at
   FROM gold.strategy_risk_reviews srr;


--
-- Name: v_agent_gold_layer_status; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_agent_gold_layer_status AS
 SELECT 'ok'::text AS state,
    max(last_run) AS refreshed_at,
    (EXTRACT(epoch FROM (now() - (max(last_run))::timestamp with time zone)) / 3600.0) AS hours_since_refresh,
    count(*) FILTER (WHERE ((status)::text = 'active'::text)) AS sources_ok,
    count(*) FILTER (WHERE ((status)::text <> 'active'::text)) AS sources_failed,
    NULL::timestamp with time zone AS locked_since,
    'Gold layer sync schedules'::text AS notes
   FROM gold.sync_schedules;


--
-- Name: v_agent_pending_work; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_agent_pending_work AS
 SELECT asset_class AS domain,
    source AS target_agent,
    strategy_id,
    status AS work_status,
    name AS strategy_name,
    created_at,
    updated_at
   FROM gold.strategy_research sr
  WHERE ((status)::text = ANY ((ARRAY['pending'::character varying, 'backtesting'::character varying, 'risk_review'::character varying, 'qa_review'::character varying])::text[]));


--
-- Name: v_agent_workflows; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_agent_workflows AS
 SELECT sr.strategy_id,
    sr.name,
    sr.status AS workflow_status,
    sr.source AS assigned_to,
    sr.rejection_reason AS workflow_result,
    COALESCE(bt.run_count, (0)::bigint) AS event_count,
    COALESCE(bt.latest_sharpe, NULL::numeric) AS latest_sharpe,
    sr.created_at AS workflow_created,
    sr.updated_at AS workflow_updated
   FROM (gold.strategy_research sr
     LEFT JOIN ( SELECT strategy_backtest_runs.strategy_id,
            count(*) AS run_count,
            max(strategy_backtest_runs.sharpe_oos) AS latest_sharpe
           FROM gold.strategy_backtest_runs
          GROUP BY strategy_backtest_runs.strategy_id) bt ON (((bt.strategy_id)::text = (sr.strategy_id)::text)));


--
-- Name: v_commodities_coverage; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_commodities_coverage AS
 SELECT count(DISTINCT ticker) AS commodities_covered,
    category,
    count(*) AS total_price_records,
    min(date) AS earliest_date,
    max(date) AS latest_date,
    max(collected_at) AS last_updated
   FROM gold.commodity_futures
  GROUP BY category;


--
-- Name: v_earnings_coverage; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_earnings_coverage AS
 SELECT count(DISTINCT ticker) AS tickers_covered,
    count(*) AS total_earnings_records,
    min(report_date) AS earliest_date,
    max(report_date) AS latest_date,
    avg(surprise_pct) AS avg_surprise,
    max(collected_at) AS last_updated
   FROM gold.earnings_data;


--
-- Name: unified_earnings; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.unified_earnings (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    report_date date NOT NULL,
    fiscal_quarter character varying(10),
    eps_estimate numeric(18,8),
    eps_actual numeric(18,8),
    eps_surprise_pct numeric(10,4),
    eps_surprise_dollar numeric(18,8),
    revenue_estimate bigint,
    revenue_actual bigint,
    revenue_surprise_pct numeric(10,4),
    time_of_day character varying(20),
    sue_score numeric(18,8),
    sue_decile integer,
    sue_category character varying(50),
    primary_source character varying(50),
    all_sources jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    price_reaction_1d numeric
);


--
-- Name: v_signal_proximity; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_signal_proximity AS
 WITH pead_universe AS (
         SELECT DISTINCT unified_earnings.ticker
           FROM silver.unified_earnings
          WHERE ((unified_earnings.report_date >= CURRENT_DATE) AND ((unified_earnings.ticker)::text ~ '^[A-Z]+$'::text))
        ), pead_next AS (
         SELECT ue.ticker,
            min(ue.report_date) AS next_earnings_date,
            (min(ue.report_date) - CURRENT_DATE) AS days_until_earnings
           FROM (silver.unified_earnings ue
             JOIN pead_universe pu ON (((ue.ticker)::text = (pu.ticker)::text)))
          WHERE (ue.report_date >= CURRENT_DATE)
          GROUP BY ue.ticker
        ), pead_last AS (
         SELECT DISTINCT ON (unified_earnings.ticker) unified_earnings.ticker,
            unified_earnings.eps_surprise_pct AS last_eps_surprise_pct,
            unified_earnings.price_reaction_1d AS last_price_reaction_1d
           FROM silver.unified_earnings
          WHERE (unified_earnings.eps_surprise_pct IS NOT NULL)
          ORDER BY unified_earnings.ticker, unified_earnings.report_date DESC
        )
 SELECT 'pead_long'::text AS strategy_id,
    p.ticker AS instrument_or_ticker,
    'earnings'::text AS signal_type,
    (abs(p.days_until_earnings))::numeric AS current_value,
    (0)::numeric AS threshold,
    (p.days_until_earnings)::numeric AS distance_to_threshold,
        CASE
            WHEN (p.days_until_earnings <= 0) THEN (100)::numeric
            ELSE GREATEST((0)::numeric, ((100)::numeric - ((p.days_until_earnings * 5))::numeric))
        END AS distance_pct,
    (p.days_until_earnings <= 0) AS signal_active,
    p.days_until_earnings AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    p.next_earnings_date,
    l.last_eps_surprise_pct,
    l.last_price_reaction_1d,
    '+5%'::text AS signal_threshold
   FROM (pead_next p
     LEFT JOIN pead_last l ON (((p.ticker)::text = (l.ticker)::text)))
UNION ALL
 SELECT 'pead_short_negative_surprise'::text AS strategy_id,
    p.ticker AS instrument_or_ticker,
    'earnings'::text AS signal_type,
    (abs(p.days_until_earnings))::numeric AS current_value,
    (0)::numeric AS threshold,
    (p.days_until_earnings)::numeric AS distance_to_threshold,
        CASE
            WHEN (p.days_until_earnings <= 0) THEN (100)::numeric
            ELSE GREATEST((0)::numeric, ((100)::numeric - ((p.days_until_earnings * 5))::numeric))
        END AS distance_pct,
    (p.days_until_earnings <= 0) AS signal_active,
    p.days_until_earnings AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    p.next_earnings_date,
    l.last_eps_surprise_pct,
    l.last_price_reaction_1d,
    '-5%'::text AS signal_threshold
   FROM (pead_next p
     LEFT JOIN pead_last l ON (((p.ticker)::text = (l.ticker)::text)))
UNION ALL
 SELECT 'vix_carry_long_equity'::text AS strategy_id,
    'VIX_CARRY'::text AS instrument_or_ticker,
    'regime'::text AS signal_type,
    (rf.rv_iv_ratio)::numeric AS current_value,
    0.50 AS threshold,
    ((rf.rv_iv_ratio - (0.50)::double precision))::numeric AS distance_to_threshold,
        CASE
            WHEN (rf.rv_iv_ratio >= (0.50)::double precision) THEN (100)::numeric
            ELSE (GREATEST((0)::double precision, ((rf.rv_iv_ratio / (0.50)::double precision) * (100)::double precision)))::numeric
        END AS distance_pct,
    (rf.rv_iv_ratio >= (0.50)::double precision) AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    (rl.regime)::text AS signal_threshold
   FROM (gold.regime_features rf
     JOIN gold.regime_label rl ON ((rf.date = rl.date)))
  WHERE (rf.date = ( SELECT max(regime_features.date) AS max
           FROM gold.regime_features))
UNION ALL
 SELECT 'cl_cot_trend'::text AS strategy_id,
    cs.instrument AS instrument_or_ticker,
    'cot'::text AS signal_type,
    (cs.cot_z)::numeric AS current_value,
    1.5 AS threshold,
    (1.5 - cs.cot_z) AS distance_to_threshold,
        CASE
            WHEN (cs.cot_z >= 1.5) THEN (100)::numeric
            ELSE GREATEST((0)::numeric, ((cs.cot_z / 1.5) * (100)::numeric))
        END AS distance_pct,
    (cs.cot_z >= 1.5) AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    'TREND'::text AS signal_threshold
   FROM gold.cot_sentiment cs
  WHERE (((cs.instrument)::text = 'CL'::text) AND (cs.date = ( SELECT max(cot_sentiment.date) AS max
           FROM gold.cot_sentiment
          WHERE ((cot_sentiment.instrument)::text = 'CL'::text))))
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
            WHEN ((s.seasonal_bias)::text <> 'neutral'::text) THEN (100)::numeric
            ELSE (0)::numeric
        END AS distance_pct,
    ((s.seasonal_bias)::text <> 'neutral'::text) AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    (s.seasonal_bias)::text AS signal_threshold
   FROM gold.commodity_seasonality s
  WHERE (((s.ticker)::text = ANY ((ARRAY['CL=F'::character varying, 'NG=F'::character varying, 'GC=F'::character varying])::text[])) AND ((s.month)::numeric = EXTRACT(month FROM CURRENT_DATE)))
UNION ALL
 SELECT 'spy_200d_reclaim_long'::text AS strategy_id,
    'SPY'::text AS instrument_or_ticker,
    'regime_transition'::text AS signal_type,
    spy.pct_from_200d AS current_value,
    (0)::numeric AS threshold,
    (- spy.pct_from_200d) AS distance_to_threshold,
        CASE
            WHEN (spy.pct_from_200d >= (0)::numeric) THEN (100)::numeric
            ELSE GREATEST((0)::numeric, ((100)::numeric + spy.pct_from_200d))
        END AS distance_pct,
    (spy.pct_from_200d >= (0)::numeric) AS signal_active,
    0 AS days_until_relevant,
    CURRENT_TIMESTAMP AS last_updated,
    NULL::date AS next_earnings_date,
    NULL::numeric AS last_eps_surprise_pct,
    NULL::numeric AS last_price_reaction_1d,
    'above_200d'::text AS signal_threshold
   FROM ( SELECT unified_prices.date,
            unified_prices.close,
            avg(unified_prices.close) OVER (ORDER BY unified_prices.date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW) AS ma200,
            (((unified_prices.close - avg(unified_prices.close) OVER (ORDER BY unified_prices.date ROWS BETWEEN 199 PRECEDING AND CURRENT ROW)) / NULLIF(unified_prices.close, (0)::numeric)) * (100)::numeric) AS pct_from_200d
           FROM silver.unified_prices
          WHERE (((unified_prices.ticker)::text = 'SPY'::text) AND (unified_prices.close IS NOT NULL))
          ORDER BY unified_prices.date DESC
         LIMIT 1) spy;


--
-- Name: vix_regime; Type: TABLE; Schema: gold; Owner: -
--

CREATE TABLE gold.vix_regime (
    date date NOT NULL,
    vix numeric(12,4),
    vix_sma60 numeric(12,4),
    vix_z60 numeric(12,4),
    regime character varying(20),
    signal_flag integer DEFAULT 0,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: v_etl_pipeline_health; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_etl_pipeline_health AS
 WITH pipeline_a AS (
         SELECT 'Pipeline A — Ingestion'::text AS pipeline,
            ( SELECT max(unified_prices.date) AS max
                   FROM silver.unified_prices) AS unified_prices_last,
            ( SELECT max(unified_earnings.report_date) AS max
                   FROM silver.unified_earnings) AS earnings_last,
            ( SELECT max(fred_macro_indicators.date) AS max
                   FROM bronze.fred_macro_indicators) AS fred_last,
            ( SELECT max((binance_crypto_ohlcv."timestamp")::date) AS max
                   FROM bronze.binance_crypto_ohlcv) AS binance_last,
            ( SELECT max((ibkr_positions_live.fetched_at)::date) AS max
                   FROM bronze.ibkr_positions_live) AS ibkr_positions_last,
            ( SELECT max((ibkr_account_summary.fetched_at)::date) AS max
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
            ( SELECT max((market_regimes."timestamp")::date) AS max
                   FROM gold.market_regimes) AS market_regimes_last,
            ( SELECT max(market_sentiment_daily.date) AS max
                   FROM gold.market_sentiment_daily) AS market_sentiment_last,
            ( SELECT max((ibkr_positions_live.fetched_at)::date) AS max
                   FROM gold.ibkr_positions_live) AS gold_ibkr_positions_last,
            ( SELECT max((ibkr_account_summary.fetched_at)::date) AS max
                   FROM gold.ibkr_account_summary) AS gold_ibkr_account_last,
            ( SELECT max(earnings_data.report_date) AS max
                   FROM gold.earnings_data) AS earnings_data_last,
            ( SELECT max(sue_scores.report_date) AS max
                   FROM gold.sue_scores) AS sue_scores_last,
            ( SELECT max((strategy_ticker_scores.updated_at)::date) AS max
                   FROM gold.strategy_ticker_scores) AS strategy_ticker_scores_last,
            ( SELECT max(strategy_backtests.run_date) AS max
                   FROM gold.strategy_backtests) AS strategy_backtests_last,
            ( SELECT max((strategy_registry.updated_at)::date) AS max
                   FROM gold.strategy_registry) AS strategy_registry_last,
            ( SELECT max(portfolio_snapshots.snapshot_date) AS max
                   FROM gold.portfolio_snapshots) AS portfolio_snapshots_last,
            ( SELECT max((paper_strategies.updated_at)::date) AS max
                   FROM gold.paper_strategies) AS paper_strategies_last,
            ( SELECT max((positions.updated_at)::date) AS max
                   FROM gold.positions) AS positions_last,
            ( SELECT max((trade_executions.executed_at)::date) AS max
                   FROM gold.trade_executions) AS trade_executions_last,
            ( SELECT max(hft_metrics.date) AS max
                   FROM gold.hft_metrics) AS hft_metrics_last,
            ( SELECT max((v_signal_proximity.last_updated)::date) AS max
                   FROM gold.v_signal_proximity) AS signal_proximity_last,
            ( SELECT max(s9_macd_signals.signal_date) AS max
                   FROM gold.s9_macd_signals) AS s9_signals_last,
            ( SELECT max(s9_paper_trades.entry_date) AS max
                   FROM gold.s9_paper_trades) AS s9_trades_last,
            ( SELECT max((seasonality_patterns.calculated_at)::date) AS max
                   FROM gold.seasonality_patterns) AS seasonality_last,
            ( SELECT max(hk_ipo_calendar.listing_date) AS max
                   FROM gold.hk_ipo_calendar) AS hk_ipo_last,
            ( SELECT max((commodity_seasonality.calculated_at)::date) AS max
                   FROM gold.commodity_seasonality) AS commodity_seasonality_last,
            ( SELECT max((asset_registry.updated_at)::date) AS max
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
            WHEN (pipeline_a.unified_prices_last < (CURRENT_DATE - 2)) THEN 'STALE'::text
            WHEN (pipeline_a.earnings_last < (CURRENT_DATE - 2)) THEN 'STALE'::text
            WHEN (pipeline_a.fred_last < (CURRENT_DATE - 35)) THEN 'STALE'::text
            WHEN (pipeline_a.binance_last < (CURRENT_DATE - 1)) THEN 'STALE'::text
            WHEN (pipeline_a.ibkr_positions_last < (CURRENT_DATE - 2)) THEN 'STALE'::text
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
            WHEN (pipeline_b.regime_features_last < (CURRENT_DATE - 2)) THEN 'STALE'::text
            WHEN (pipeline_b.regime_label_last < (CURRENT_DATE - 2)) THEN 'STALE'::text
            WHEN (pipeline_b.stock_metrics_last < (CURRENT_DATE - 2)) THEN 'STALE'::text
            WHEN (pipeline_b.kpis_last < (CURRENT_DATE - 2)) THEN 'STALE'::text
            ELSE 'OK'::text
        END AS status
   FROM pipeline_b;


--
-- Name: v_latest_sue_scores; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_latest_sue_scores AS
 SELECT s.ticker,
    s.report_date,
    s.sue,
    s.sue_decile,
    s.sue_category,
    e.actual_eps,
    e.estimate_eps,
    e.surprise_pct
   FROM (gold.sue_scores s
     JOIN gold.earnings_data e ON ((((s.ticker)::text = (e.ticker)::text) AND (s.report_date = e.report_date))))
  WHERE (s.report_date >= (now() - '30 days'::interval))
  ORDER BY s.sue DESC;


--
-- Name: v_paper_daily_runs; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_paper_daily_runs AS
 SELECT run_date,
    run_type,
    signals_eval,
    orders_placed,
    orders_skipped,
    gate_reasons,
    total_pnl,
    drawdown_pct,
    status,
    duration_ms
   FROM gold.paper_run_log
  WHERE (run_date = CURRENT_DATE)
  ORDER BY id DESC;


--
-- Name: v_paper_open_positions; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_paper_open_positions AS
 WITH latest_prices AS (
         SELECT DISTINCT ON (unified_prices.ticker) unified_prices.ticker,
            unified_prices.close AS latest_close,
            unified_prices.date AS price_date
           FROM silver.unified_prices
          WHERE (unified_prices.close IS NOT NULL)
          ORDER BY unified_prices.ticker, unified_prices.date DESC
        )
 SELECT pt.strategy_id,
    pt.instrument,
    pt.ticker,
    pt.direction,
    pt.size,
    pt.n_shares,
    pt.entry_price,
    COALESCE(lp.latest_close, pt.entry_price) AS current_price,
        CASE
            WHEN ((pt.direction = 'long'::text) AND (pt.entry_price > (0)::numeric)) THEN (((COALESCE(lp.latest_close, pt.entry_price) - pt.entry_price) / pt.entry_price) * (100)::numeric)
            WHEN ((pt.direction = 'short'::text) AND (pt.entry_price > (0)::numeric)) THEN (((pt.entry_price - COALESCE(lp.latest_close, pt.entry_price)) / pt.entry_price) * (100)::numeric)
            ELSE NULL::numeric
        END AS unrealised_pnl_pct,
        CASE
            WHEN ((pt.n_shares IS NOT NULL) AND (pt.entry_price > (0)::numeric)) THEN ((COALESCE(lp.latest_close, pt.entry_price) - pt.entry_price) * (pt.n_shares)::numeric)
            ELSE NULL::numeric
        END AS unrealised_pnl_usd,
    (pt.ts)::date AS entry_date,
    (CURRENT_DATE - (pt.ts)::date) AS days_held,
    pt.status,
        CASE
            WHEN (lp.latest_close IS NOT NULL) THEN 'eod_proxy'::text
            ELSE 'live'::text
        END AS price_source,
    lp.price_date AS price_as_of
   FROM (gold.paper_trades pt
     LEFT JOIN latest_prices lp ON ((pt.ticker = (lp.ticker)::text)))
  WHERE ((pt.status = 'open'::text) OR ((pt.exit_price IS NULL) AND (pt.status IS DISTINCT FROM 'closed'::text)));


--
-- Name: v_paper_system_status; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_paper_system_status AS
 SELECT rl.regime AS regime_label,
    rl.confidence AS regime_confidence,
    rl.override_used AS regime_override,
    rl.date AS regime_date,
    (CURRENT_DATE - rl.date) AS regime_staleness_days,
    first_value(rl.date) OVER (ORDER BY rl.date DESC) AS regime_since,
    pr.run_date AS last_run_date,
    pr.run_type AS last_run_type,
    pr.status AS last_run_status,
    pr.orders_placed AS last_orders_placed,
    pr.orders_skipped AS last_orders_skipped,
    32000 AS paper_nav_usd,
    250000 AS paper_nav_hkd
   FROM (gold.regime_label rl
     CROSS JOIN ( SELECT paper_run_log.run_date,
            paper_run_log.run_type,
            paper_run_log.status,
            paper_run_log.orders_placed,
            paper_run_log.orders_skipped
           FROM gold.paper_run_log
          WHERE (paper_run_log.status = 'ok'::text)
          ORDER BY paper_run_log.id DESC
         LIMIT 1) pr)
  WHERE (rl.date = ( SELECT max(regime_label.date) AS max
           FROM gold.regime_label));


--
-- Name: v_paper_trade_history; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_paper_trade_history AS
 SELECT id,
    strategy_id,
    instrument,
    ticker,
    direction,
    size AS contracts,
    n_shares AS shares,
    entry_price,
    exit_price,
    pnl,
    round(
        CASE
            WHEN (entry_price > (0)::numeric) THEN ((pnl / (entry_price * COALESCE(size, (n_shares)::numeric, (1)::numeric))) * (100)::numeric)
            ELSE (0)::numeric
        END, 2) AS pnl_pct,
    regime,
    ic_at_entry,
    ts AS opened_at,
    updated_at AS closed_at,
    EXTRACT(day FROM (updated_at - ts)) AS hold_days
   FROM gold.paper_trades p
  WHERE ((status = 'closed'::text) AND (rehearsal = false) AND (ts >= (now() - '30 days'::interval)))
  ORDER BY ts DESC;


--
-- Name: v_paper_trade_summary; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_paper_trade_summary AS
 SELECT count(*) AS total_trades,
    round((((sum(
        CASE
            WHEN (pnl > (0)::numeric) THEN 1
            ELSE 0
        END))::numeric / (NULLIF(count(*), 0))::numeric) * (100)::numeric), 1) AS win_rate_pct,
    round(sum(pnl), 2) AS total_pnl,
    round(avg(pnl), 2) AS avg_pnl,
    round(min(pnl), 2) AS max_loss,
    round(max(pnl), 2) AS max_win,
    ( SELECT max(paper_run_log.drawdown_pct) AS max
           FROM gold.paper_run_log
          WHERE (paper_run_log.run_date >= (now() - '30 days'::interval))) AS max_drawdown_pct
   FROM gold.paper_trades p
  WHERE ((status = 'closed'::text) AND (rehearsal = false) AND (ts >= (now() - '30 days'::interval)));


--
-- Name: v_s015_macro_enriched; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_s015_macro_enriched AS
 SELECT month,
    cpi_yoy,
    treasury_10y_avg,
    oil_avg_price,
    xle_close,
    xlp_close,
    xly_close,
        CASE
            WHEN (cpi_yoy > (4)::numeric) THEN 'HIGH_INFLATION'::text
            WHEN (cpi_yoy > 2.5) THEN 'MODERATE_INFLATION'::text
            WHEN (cpi_yoy > (0)::numeric) THEN 'LOW_INFLATION'::text
            ELSE 'DEFLATION'::text
        END AS inflation_regime,
        CASE
            WHEN (treasury_10y_avg > (4)::numeric) THEN 'HIGH_RATES'::text
            WHEN (treasury_10y_avg > 2.5) THEN 'RISING_RATES'::text
            WHEN (treasury_10y_avg > 1.5) THEN 'NEUTRAL'::text
            ELSE 'LOW_RATES'::text
        END AS rate_regime,
        CASE
            WHEN (oil_avg_price > (80)::numeric) THEN 'HIGH_OIL'::text
            WHEN (oil_avg_price > (60)::numeric) THEN 'MODERATE_OIL'::text
            ELSE 'LOW_OIL'::text
        END AS energy_regime,
    lag(xle_close) OVER (ORDER BY month) AS xle_prev,
    lag(xlp_close) OVER (ORDER BY month) AS xlp_prev,
    lag(xly_close) OVER (ORDER BY month) AS xly_prev,
        CASE
            WHEN ((xly_close > lag(xly_close) OVER (ORDER BY month)) AND ((xly_close - lag(xly_close) OVER (ORDER BY month)) > (xlp_close - lag(xlp_close) OVER (ORDER BY month)))) THEN 'RISK_ON'::text
            ELSE 'RISK_OFF'::text
        END AS risk_regime
   FROM gold.v_s015_sector_rotation s
  ORDER BY month DESC;


--
-- Name: v_seasonal_opportunities; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_seasonal_opportunities AS
 SELECT ticker,
    name,
    category,
    month,
    avg_return,
    seasonal_bias,
    CURRENT_DATE AS "current_date",
    EXTRACT(month FROM CURRENT_DATE) AS current_month
   FROM gold.commodity_seasonality
  WHERE (((seasonal_bias)::text = ANY ((ARRAY['STRONG_BULL'::character varying, 'STRONG_BEAR'::character varying])::text[])) AND ((month)::numeric = EXTRACT(month FROM CURRENT_DATE)))
  ORDER BY (abs(avg_return)) DESC;


--
-- Name: v_strategy_book; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_strategy_book AS
 WITH latest_backtest AS (
         SELECT DISTINCT ON (strategy_backtest_runs.strategy_id) strategy_backtest_runs.strategy_id,
            strategy_backtest_runs.sharpe_oos AS sharpe_ratio,
            strategy_backtest_runs.win_rate_oos AS win_rate,
            strategy_backtest_runs.created_at AS backtest_date
           FROM gold.strategy_backtest_runs
          ORDER BY strategy_backtest_runs.strategy_id, strategy_backtest_runs.created_at DESC
        )
 SELECT s.strategy_id,
    s.name,
    s.status,
    s.asset_class,
    s.entry_logic,
    s.exit_logic,
    s.source AS agent_source,
    b.sharpe_ratio,
    b.win_rate,
    b.backtest_date,
        CASE s.status
            WHEN 'approved'::text THEN 1
            WHEN 'backtesting'::text THEN 2
            WHEN 'rejected'::text THEN 3
            ELSE 4
        END AS sort_order,
    t.entry_price AS last_entry_price,
    t.ts AS last_traded_at,
    t.direction AS last_direction
   FROM ((gold.strategy_research s
     LEFT JOIN latest_backtest b ON (((b.strategy_id)::text = (s.strategy_id)::text)))
     LEFT JOIN ( SELECT DISTINCT ON (paper_trades.strategy_id) paper_trades.strategy_id,
            paper_trades.entry_price,
            paper_trades.ts,
            paper_trades.direction
           FROM gold.paper_trades
          WHERE (paper_trades.rehearsal = false)
          ORDER BY paper_trades.strategy_id, paper_trades.ts DESC) t ON ((t.strategy_id = (s.strategy_id)::text)))
  ORDER BY
        CASE s.status
            WHEN 'approved'::text THEN 1
            WHEN 'backtesting'::text THEN 2
            WHEN 'rejected'::text THEN 3
            ELSE 4
        END, s.strategy_id;


--
-- Name: v_strategy_book_extended; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_strategy_book_extended AS
 WITH latest_backtest AS (
         SELECT DISTINCT ON (strategy_backtest_runs.strategy_id) strategy_backtest_runs.strategy_id,
            strategy_backtest_runs.sharpe_oos AS sharpe_ratio,
            strategy_backtest_runs.win_rate_oos AS win_rate,
            strategy_backtest_runs.created_at AS backtest_date
           FROM gold.strategy_backtest_runs
          ORDER BY strategy_backtest_runs.strategy_id, strategy_backtest_runs.created_at DESC
        ), latest_trade AS (
         SELECT DISTINCT ON (paper_trades.strategy_id) paper_trades.strategy_id,
            paper_trades.direction,
            paper_trades.entry_price,
            paper_trades.ts AS last_traded_at
           FROM gold.paper_trades
          WHERE (paper_trades.rehearsal = false)
          ORDER BY paper_trades.strategy_id, paper_trades.ts DESC
        ), annual_pnl AS (
         SELECT DISTINCT ON (strategy_backtest_runs.strategy_id) strategy_backtest_runs.strategy_id,
            strategy_backtest_runs.annual_pnl_2024,
            strategy_backtest_runs.annual_pnl_2025,
            strategy_backtest_runs.annual_pnl_2026
           FROM gold.strategy_backtest_runs
          WHERE ((strategy_backtest_runs.annual_pnl_2024 IS NOT NULL) OR (strategy_backtest_runs.annual_pnl_2025 IS NOT NULL) OR (strategy_backtest_runs.annual_pnl_2026 IS NOT NULL))
          ORDER BY strategy_backtest_runs.strategy_id, strategy_backtest_runs.created_at DESC
        )
 SELECT s.strategy_id,
    s.name,
    s.status,
    s.asset_class,
    s.entry_logic,
    s.exit_logic,
    s.source,
    b.sharpe_ratio,
    b.win_rate,
    b.backtest_date,
    t.direction AS last_direction,
    t.entry_price AS last_entry_price,
    t.last_traded_at,
    pnl.annual_pnl_2024,
    pnl.annual_pnl_2025,
    pnl.annual_pnl_2026,
        CASE s.status
            WHEN 'approved'::text THEN 1
            WHEN 'backtesting'::text THEN 2
            WHEN 'rejected'::text THEN 3
            ELSE 4
        END AS sort_order,
        CASE s.strategy_id
            WHEN 'cl_cot_trend'::text THEN 'CL COT Trend'::character varying
            WHEN 'cot_contrarian_extreme'::text THEN 'COT Contrarian'::character varying
            WHEN 'gc_cot_contrarian_inverse'::text THEN 'GC COT Inverse'::character varying
            WHEN 'vix_spike_fade_entry'::text THEN 'VIX Spike Fade'::character varying
            WHEN 'rsi_oversold_long'::text THEN 'RSI Oversold'::character varying
            WHEN 'pead_long'::text THEN 'Post-Earnings Drift'::character varying
            WHEN 'btc_momentum_long'::text THEN 'BTC Momentum'::character varying
            WHEN 'crude_seasonal'::text THEN 'Crude Seasonal'::character varying
            WHEN 'natgas_seasonal'::text THEN 'NatGas Seasonal'::character varying
            WHEN 'gold_seasonal'::text THEN 'Gold Seasonal'::character varying
            ELSE s.name
        END AS display_name,
        CASE s.strategy_id
            WHEN 'cl_cot_trend'::text THEN 'MCL'::text
            WHEN 'cot_contrarian_extreme'::text THEN 'M6E'::text
            WHEN 'gc_cot_contrarian_inverse'::text THEN 'MGC'::text
            WHEN 'vix_spike_fade_entry'::text THEN 'MES'::text
            WHEN 'rsi_oversold_long'::text THEN 'MES'::text
            WHEN 'pead_long'::text THEN 'STK'::text
            WHEN 'btc_momentum_long'::text THEN 'BTC'::text
            WHEN 'crude_seasonal'::text THEN 'MCL'::text
            WHEN 'natgas_seasonal'::text THEN 'QG'::text
            WHEN 'gold_seasonal'::text THEN 'MGC'::text
            ELSE '—'::text
        END AS instrument,
        CASE s.strategy_id
            WHEN 'cl_cot_trend'::text THEN 'TREND'::text
            WHEN 'cot_contrarian_extreme'::text THEN 'MEAN_REV'::text
            WHEN 'gc_cot_contrarian_inverse'::text THEN 'MEAN_REV'::text
            WHEN 'vix_spike_fade_entry'::text THEN 'VOLATILE'::text
            WHEN 'rsi_oversold_long'::text THEN 'MEAN_REV'::text
            WHEN 'pead_long'::text THEN 'ANY'::text
            WHEN 'btc_momentum_long'::text THEN 'TREND'::text
            WHEN 'crude_seasonal'::text THEN 'ANY'::text
            WHEN 'natgas_seasonal'::text THEN 'ANY'::text
            WHEN 'gold_seasonal'::text THEN 'ANY'::text
            ELSE 'ANY'::text
        END AS regime_scope,
        CASE s.strategy_id
            WHEN 'cl_cot_trend'::text THEN 20805
            WHEN 'cot_contrarian_extreme'::text THEN 103746
            WHEN 'gc_cot_contrarian_inverse'::text THEN 818624
            WHEN 'vix_spike_fade_entry'::text THEN 609180
            WHEN 'rsi_oversold_long'::text THEN 609180
            WHEN 'pead_long'::text THEN 3168
            WHEN 'crude_seasonal'::text THEN 73999
            WHEN 'natgas_seasonal'::text THEN 75097
            ELSE NULL::integer
        END AS min_nav_usd
   FROM (((gold.strategy_research s
     LEFT JOIN latest_backtest b ON (((b.strategy_id)::text = (s.strategy_id)::text)))
     LEFT JOIN latest_trade t ON ((t.strategy_id = (s.strategy_id)::text)))
     LEFT JOIN annual_pnl pnl ON (((pnl.strategy_id)::text = (s.strategy_id)::text)))
  ORDER BY
        CASE s.status
            WHEN 'approved'::text THEN 1
            WHEN 'backtesting'::text THEN 2
            WHEN 'rejected'::text THEN 3
            ELSE 4
        END, s.strategy_id;


--
-- Name: v_upcoming_events; Type: VIEW; Schema: gold; Owner: -
--

CREATE VIEW gold.v_upcoming_events AS
 SELECT 'earnings'::text AS event_category,
    unified_earnings.report_date AS event_date,
    unified_earnings.ticker AS event_label,
    concat(unified_earnings.ticker, ' earnings — est EPS: ', (round((unified_earnings.eps_estimate)::numeric, 2))::text) AS description,
    'pead_long'::text AS related_strategy,
    (unified_earnings.report_date - CURRENT_DATE) AS days_away
   FROM silver.unified_earnings
  WHERE (((unified_earnings.report_date >= CURRENT_DATE) AND (unified_earnings.report_date <= (CURRENT_DATE + '14 days'::interval))) AND (unified_earnings.eps_actual IS NULL))
UNION ALL
 SELECT 'macro'::text AS event_category,
    macro_event_flags.date AS event_date,
        CASE
            WHEN (macro_event_flags.cpi_flag = 1) THEN 'CPI'::text
            WHEN (macro_event_flags.nfp_flag = 1) THEN 'NFP'::text
            WHEN (macro_event_flags.fed_funds_flag = 1) THEN 'FED_FUNDS'::text
            WHEN (macro_event_flags.eia_flag = 1) THEN 'EIA'::text
            ELSE 'MACRO'::text
        END AS event_label,
    concat(
        CASE
            WHEN (macro_event_flags.cpi_flag = 1) THEN 'CPI'::text
            WHEN (macro_event_flags.nfp_flag = 1) THEN 'NFP'::text
            WHEN (macro_event_flags.fed_funds_flag = 1) THEN 'FED_FUNDS'::text
            WHEN (macro_event_flags.eia_flag = 1) THEN 'EIA'::text
            ELSE 'MACRO'::text
        END, ' release — severity: ', macro_event_flags.severity) AS description,
        CASE
            WHEN (macro_event_flags.nfp_flag = 1) THEN 'nfp_fx_trade'::text
            ELSE 'macro_event'::text
        END AS related_strategy,
    (macro_event_flags.date - CURRENT_DATE) AS days_away
   FROM gold.macro_event_flags
  WHERE (((macro_event_flags.date >= CURRENT_DATE) AND (macro_event_flags.date <= (CURRENT_DATE + '14 days'::interval))) AND (macro_event_flags.event_flag = 1))
  ORDER BY 2;


--
-- Name: gold_layer_state; Type: TABLE; Schema: openclaw_researcher; Owner: -
--

CREATE TABLE openclaw_researcher.gold_layer_state (
    id integer DEFAULT 1 NOT NULL,
    state text,
    sources_ok jsonb,
    sources_failed jsonb,
    locked_since timestamp with time zone,
    refreshed_at timestamp with time zone,
    notes text,
    updated_at timestamp with time zone DEFAULT now()
);


--
-- Name: benchmark_indices; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.benchmark_indices (
    date date NOT NULL,
    ticker character varying(10) NOT NULL,
    name character varying,
    close numeric,
    change_pct numeric,
    ma_50 numeric,
    ma_200 numeric,
    rsi_14 numeric
);


--
-- Name: daily_market_rca; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.daily_market_rca (
    id integer NOT NULL,
    date date NOT NULL,
    market character varying(10) NOT NULL,
    ticker character varying(20) NOT NULL,
    company_name character varying(100),
    daily_return_pct numeric(10,4),
    rank integer,
    direction character varying(10),
    rca_category character varying(50),
    rca_summary text,
    related_tickers text,
    news_headlines text,
    strategy_hypothesis text,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: daily_market_rca_id_seq; Type: SEQUENCE; Schema: research_sandbox; Owner: -
--

CREATE SEQUENCE research_sandbox.daily_market_rca_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_market_rca_id_seq; Type: SEQUENCE OWNED BY; Schema: research_sandbox; Owner: -
--

ALTER SEQUENCE research_sandbox.daily_market_rca_id_seq OWNED BY research_sandbox.daily_market_rca.id;


--
-- Name: daily_strategy_ideas; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.daily_strategy_ideas (
    id integer NOT NULL,
    date date NOT NULL,
    strategy_name character varying(100) NOT NULL,
    hypothesis text,
    entry_rules text,
    exit_rules text,
    universe character varying(200),
    holding_period character varying(50),
    frequency character varying(50),
    country character varying(50),
    asset_type character varying(50),
    pattern_type character varying(50),
    status character varying(20) DEFAULT 'PENDING_BACKTEST'::character varying,
    backtest_result_id integer,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: daily_strategy_ideas_id_seq; Type: SEQUENCE; Schema: research_sandbox; Owner: -
--

CREATE SEQUENCE research_sandbox.daily_strategy_ideas_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: daily_strategy_ideas_id_seq; Type: SEQUENCE OWNED BY; Schema: research_sandbox; Owner: -
--

ALTER SEQUENCE research_sandbox.daily_strategy_ideas_id_seq OWNED BY research_sandbox.daily_strategy_ideas.id;


--
-- Name: ohlcv_backtest; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.ohlcv_backtest (
    date date,
    ticker character varying,
    sector character varying,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    vwap numeric,
    rsi_14 numeric,
    macd_line numeric,
    macd_signal numeric,
    macd_hist numeric,
    sma_50 numeric,
    sma_200 numeric,
    stoch_k numeric,
    stoch_d numeric,
    adx numeric,
    adx_plus_di numeric,
    adx_minus_di numeric
);


--
-- Name: research_log; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.research_log (
    id integer NOT NULL,
    log_date date DEFAULT CURRENT_DATE NOT NULL,
    agent_name character varying(50) DEFAULT 'research_agent'::character varying NOT NULL,
    log_level character varying(20) DEFAULT 'INFO'::character varying NOT NULL,
    message text NOT NULL,
    metadata jsonb,
    created_at timestamp without time zone DEFAULT now()
);


--
-- Name: research_log_id_seq; Type: SEQUENCE; Schema: research_sandbox; Owner: -
--

CREATE SEQUENCE research_sandbox.research_log_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: research_log_id_seq; Type: SEQUENCE OWNED BY; Schema: research_sandbox; Owner: -
--

ALTER SEQUENCE research_sandbox.research_log_id_seq OWNED BY research_sandbox.research_log.id;


--
-- Name: spy_ohlcv; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.spy_ohlcv (
    date date NOT NULL,
    ticker character varying(10),
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    dividends numeric,
    splits numeric
);


--
-- Name: strategy_universe; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.strategy_universe (
    strategy_id character varying(50),
    ticker character varying(20),
    market character varying(10),
    sector character varying(50)
);


--
-- Name: ticker_sectors; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.ticker_sectors (
    ticker character varying(20) NOT NULL,
    sector character varying(50),
    market character varying(10)
);


--
-- Name: vix_data; Type: TABLE; Schema: research_sandbox; Owner: -
--

CREATE TABLE research_sandbox.vix_data (
    date date NOT NULL,
    ticker character varying(10),
    name character varying,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume bigint,
    change_pct numeric,
    rsi_14 numeric,
    volatility_21d numeric,
    is_volatility_index boolean
);


--
-- Name: agent_tasks; Type: TABLE; Schema: shared; Owner: -
--

CREATE TABLE shared.agent_tasks (
    id integer NOT NULL,
    from_agent character varying(50) NOT NULL,
    to_agent character varying(50) NOT NULL,
    task_type character varying(100) NOT NULL,
    payload jsonb NOT NULL,
    priority character varying(20) DEFAULT 'normal'::character varying,
    status character varying(20) DEFAULT 'pending'::character varying,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now(),
    completed_at timestamp without time zone,
    response jsonb,
    error_message text
);


--
-- Name: agent_tasks_id_seq; Type: SEQUENCE; Schema: shared; Owner: -
--

CREATE SEQUENCE shared.agent_tasks_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: agent_tasks_id_seq; Type: SEQUENCE OWNED BY; Schema: shared; Owner: -
--

ALTER SEQUENCE shared.agent_tasks_id_seq OWNED BY shared.agent_tasks.id;


--
-- Name: v_pending_tasks; Type: VIEW; Schema: shared; Owner: -
--

CREATE VIEW shared.v_pending_tasks AS
 SELECT id,
    from_agent,
    to_agent,
    task_type,
    payload,
    priority,
    status,
    created_at,
    updated_at,
    completed_at,
    response,
    error_message
   FROM shared.agent_tasks
  WHERE ((status)::text = 'pending'::text)
  ORDER BY priority DESC, created_at;


--
-- Name: asset_registry; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.asset_registry (
    id integer NOT NULL,
    ticker character varying(50) NOT NULL,
    name character varying(200),
    asset_class character varying(20) NOT NULL,
    market character varying(20),
    sector character varying(100),
    industry character varying(100),
    currency character varying(10) DEFAULT 'USD'::character varying,
    is_active boolean DEFAULT true,
    is_tradeable boolean DEFAULT true,
    lot_size numeric(18,8),
    tick_size numeric(18,8),
    min_order_size numeric(18,8),
    max_order_size numeric(18,8),
    exchange character varying(50),
    source character varying(50),
    first_traded_date date,
    metadata jsonb,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: asset_registry_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.asset_registry_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: asset_registry_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.asset_registry_id_seq OWNED BY silver.asset_registry.id;


--
-- Name: cot_euro_fx_daily; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.cot_euro_fx_daily (
    instrument character varying NOT NULL,
    date date NOT NULL,
    report_date date NOT NULL,
    noncomm_long bigint,
    noncomm_short bigint,
    net_noncomm bigint,
    cot_z numeric,
    calculated_at timestamp with time zone DEFAULT now()
);


--
-- Name: crypto_ohlcv_normalized; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.crypto_ohlcv_normalized (
    id bigint NOT NULL,
    symbol character varying(20) NOT NULL,
    "interval" character varying(10) NOT NULL,
    "timestamp" timestamp without time zone NOT NULL,
    open numeric,
    high numeric,
    low numeric,
    close numeric,
    volume numeric,
    quote_volume numeric,
    trades_count integer,
    taker_buy_volume numeric,
    taker_buy_quote_volume numeric,
    returns numeric,
    log_returns numeric,
    vwap numeric,
    volatility_20 numeric,
    true_range numeric,
    atr_14 numeric,
    market_cap_proxy numeric,
    data_source character varying(20),
    normalized_at timestamp without time zone
);


--
-- Name: crypto_ohlcv_normalized_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.crypto_ohlcv_normalized_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: crypto_ohlcv_normalized_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.crypto_ohlcv_normalized_id_seq OWNED BY silver.crypto_ohlcv_normalized.id;


--
-- Name: earnings_calendar; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.earnings_calendar (
    id integer NOT NULL,
    report_date date NOT NULL,
    ticker character varying(16) NOT NULL,
    eps_estimate numeric,
    eps_actual numeric,
    eps_surprise_pct numeric,
    price_reaction_1d numeric,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: earnings_calendar_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.earnings_calendar_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: earnings_calendar_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.earnings_calendar_id_seq OWNED BY silver.earnings_calendar.id;


--
-- Name: funding_rates_daily; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.funding_rates_daily (
    symbol text NOT NULL,
    date date NOT NULL,
    funding_rate_8h numeric,
    funding_z numeric,
    n_obs integer DEFAULT 0,
    calculated_at timestamp with time zone DEFAULT now()
);


--
-- Name: historical_news; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.historical_news (
    date timestamp without time zone NOT NULL,
    id integer NOT NULL,
    category character varying(50),
    entity_name character varying(100),
    headline text,
    source character varying(100)
);


--
-- Name: historical_news_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.historical_news_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: historical_news_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.historical_news_id_seq OWNED BY silver.historical_news.id;


--
-- Name: historical_stock_data; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.historical_stock_data (
    date timestamp without time zone NOT NULL,
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    open double precision,
    high double precision,
    low double precision,
    close double precision,
    volume double precision,
    returns double precision
);


--
-- Name: historical_stock_data_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.historical_stock_data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: historical_stock_data_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.historical_stock_data_id_seq OWNED BY silver.historical_stock_data.id;


--
-- Name: macro_event_calendar; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.macro_event_calendar (
    date date NOT NULL,
    cpi_flag integer DEFAULT 0,
    nfp_flag integer DEFAULT 0,
    fed_funds_flag integer DEFAULT 0,
    event_flag integer DEFAULT 0,
    updated_at timestamp with time zone DEFAULT now(),
    eia_flag smallint DEFAULT 0,
    severity smallint DEFAULT 0
);


--
-- Name: market_indices; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.market_indices (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    name character varying(100),
    market character varying(10),
    region character varying(50),
    currency character varying(5),
    date date NOT NULL,
    open numeric(15,4),
    high numeric(15,4),
    low numeric(15,4),
    close numeric(15,4),
    volume bigint,
    change_pct numeric(8,4),
    change_amount numeric(15,4),
    ytd_change numeric(8,4),
    _52_week_high numeric(15,4),
    _52_week_low numeric(15,4),
    _52_week_range_pct numeric(8,4),
    ma_50 numeric(15,4),
    ma_200 numeric(15,4),
    above_ma_50 boolean,
    above_ma_200 boolean,
    rsi_14 numeric(5,2),
    is_volatility_index boolean DEFAULT false,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: market_indices_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.market_indices_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: market_indices_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.market_indices_id_seq OWNED BY silver.market_indices.id;


--
-- Name: quarantine; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.quarantine (
    id bigint NOT NULL,
    source_table character varying(100) NOT NULL,
    source_id bigint NOT NULL,
    reason character varying(100) NOT NULL,
    severity character varying(10) DEFAULT 'warn'::character varying,
    details jsonb,
    quarantined_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone,
    resolved_by character varying(50)
);


--
-- Name: quarantine_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.quarantine_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: quarantine_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.quarantine_id_seq OWNED BY silver.quarantine.id;


--
-- Name: technical_indicators; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.technical_indicators (
    id bigint NOT NULL,
    ticker character varying(50) NOT NULL,
    date date NOT NULL,
    sma_20 numeric(28,8),
    sma_50 numeric(28,8),
    sma_200 numeric(28,8),
    ema_12 numeric(28,8),
    ema_26 numeric(28,8),
    rsi_14 numeric(8,4),
    macd_line numeric(28,8),
    macd_signal numeric(28,8),
    macd_histogram numeric(28,8),
    bb_upper numeric(28,8),
    bb_middle numeric(28,8),
    bb_lower numeric(28,8),
    bb_width numeric(8,4),
    atr_14 numeric(28,8),
    volatility_20d numeric(8,4),
    volume_sma_20 numeric(28,8),
    volume_ratio numeric(8,4),
    price_vs_sma50_pct numeric(8,4),
    price_vs_sma200_pct numeric(8,4),
    calculated_at timestamp without time zone DEFAULT now(),
    stoch_k numeric(8,4),
    stoch_d numeric(8,4),
    stoch_oversold boolean,
    stoch_overbought boolean,
    adx numeric(8,4),
    adx_plus_di numeric(8,4),
    adx_minus_di numeric(8,4),
    adx_trend_strength character varying(20),
    psar numeric(15,4),
    psar_direction character varying(10),
    psar_flip boolean,
    vwap numeric(15,4)
);


--
-- Name: technical_indicators_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.technical_indicators_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: technical_indicators_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.technical_indicators_id_seq OWNED BY silver.technical_indicators.id;


--
-- Name: unified_earnings_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.unified_earnings_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: unified_earnings_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.unified_earnings_id_seq OWNED BY silver.unified_earnings.id;


--
-- Name: unified_ipo_calendar; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.unified_ipo_calendar (
    id integer NOT NULL,
    ticker character varying(20) NOT NULL,
    stock_name character varying(255) NOT NULL,
    listing_date date NOT NULL,
    offer_price numeric(10,4) NOT NULL,
    currency character varying(3) DEFAULT 'HKD'::character varying,
    market_cap_hkd numeric(20,2),
    market_cap_usd numeric(20,2),
    sector character varying(100),
    sub_sector character varying(100),
    sponsor character varying(255),
    underwriters text[],
    shares_offered bigint,
    greenshoe_shares bigint,
    total_shares_post_ipo bigint,
    free_float_pct numeric(5,2),
    board character varying(20),
    oversubscription_retail numeric(10,2),
    oversubscription_institutional numeric(10,2),
    cornerstone_total_pct numeric(5,2),
    cornerstone_investors_count integer,
    lockup_period_days integer,
    greenshoe_pct numeric(5,2),
    first_seen_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone DEFAULT now()
);


--
-- Name: unified_ipo_calendar_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.unified_ipo_calendar_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: unified_ipo_calendar_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.unified_ipo_calendar_id_seq OWNED BY silver.unified_ipo_calendar.id;


--
-- Name: unified_ipo_performance; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.unified_ipo_performance (
    ticker character varying(10) NOT NULL,
    ipo_date date,
    return_1m double precision,
    return_3m double precision
);


--
-- Name: unified_prices_new_id_seq; Type: SEQUENCE; Schema: silver; Owner: -
--

CREATE SEQUENCE silver.unified_prices_new_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: unified_prices_new_id_seq; Type: SEQUENCE OWNED BY; Schema: silver; Owner: -
--

ALTER SEQUENCE silver.unified_prices_new_id_seq OWNED BY silver.unified_prices.id;


--
-- Name: vix_indicators; Type: TABLE; Schema: silver; Owner: -
--

CREATE TABLE silver.vix_indicators (
    ticker character varying NOT NULL,
    date date NOT NULL,
    vix numeric,
    vix_sma60 numeric,
    vix_z60 numeric,
    calculated_at timestamp with time zone DEFAULT now()
);


--
-- Name: binance_crypto_ohlcv id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.binance_crypto_ohlcv ALTER COLUMN id SET DEFAULT nextval('bronze.binance_crypto_ohlcv_id_seq'::regclass);


--
-- Name: binance_funding_rates id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.binance_funding_rates ALTER COLUMN id SET DEFAULT nextval('bronze.binance_funding_rates_id_seq'::regclass);


--
-- Name: data_quality_log id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.data_quality_log ALTER COLUMN id SET DEFAULT nextval('bronze.data_quality_log_id_seq'::regclass);


--
-- Name: earnings_calendar id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.earnings_calendar ALTER COLUMN id SET DEFAULT nextval('bronze.earnings_calendar_id_seq'::regclass);


--
-- Name: fmp_institutional_holdings id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.fmp_institutional_holdings ALTER COLUMN id SET DEFAULT nextval('bronze.fmp_institutional_holdings_id_seq'::regclass);


--
-- Name: fx_prices id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.fx_prices ALTER COLUMN id SET DEFAULT nextval('bronze.fx_prices_id_seq'::regclass);


--
-- Name: hkex_ipo_calendar_raw id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.hkex_ipo_calendar_raw ALTER COLUMN id SET DEFAULT nextval('bronze.hkex_ipo_calendar_raw_id_seq'::regclass);


--
-- Name: ibkr_contracts id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_contracts ALTER COLUMN id SET DEFAULT nextval('bronze.ibkr_contracts_id_seq'::regclass);


--
-- Name: ibkr_fx_bars id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_fx_bars ALTER COLUMN id SET DEFAULT nextval('bronze.ibkr_fx_bars_id_seq'::regclass);


--
-- Name: ibkr_fx_ticks id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_fx_ticks ALTER COLUMN id SET DEFAULT nextval('bronze.ibkr_fx_ticks_id_seq'::regclass);


--
-- Name: ibkr_historical_bars id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_historical_bars ALTER COLUMN id SET DEFAULT nextval('bronze.ibkr_historical_bars_id_seq'::regclass);


--
-- Name: ibkr_orders id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_orders ALTER COLUMN id SET DEFAULT nextval('bronze.ibkr_orders_id_seq'::regclass);


--
-- Name: ibkr_positions id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_positions ALTER COLUMN id SET DEFAULT nextval('bronze.ibkr_positions_id_seq'::regclass);


--
-- Name: ibkr_positions_live id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_positions_live ALTER COLUMN id SET DEFAULT nextval('bronze.ibkr_positions_live_id_seq'::regclass);


--
-- Name: institutional_holdings id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.institutional_holdings ALTER COLUMN id SET DEFAULT nextval('bronze.institutional_holdings_id_seq'::regclass);


--
-- Name: manual_earnings id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.manual_earnings ALTER COLUMN id SET DEFAULT nextval('bronze.manual_earnings_id_seq'::regclass);


--
-- Name: raw_news id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.raw_news ALTER COLUMN id SET DEFAULT nextval('bronze.raw_news_id_seq'::regclass);


--
-- Name: raw_stock_data id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.raw_stock_data ALTER COLUMN id SET DEFAULT nextval('bronze.raw_stock_data_id_seq'::regclass);


--
-- Name: yf_commodity_futures id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.yf_commodity_futures ALTER COLUMN id SET DEFAULT nextval('bronze.yf_commodity_futures_id_seq'::regclass);


--
-- Name: yf_prices id; Type: DEFAULT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.yf_prices ALTER COLUMN id SET DEFAULT nextval('bronze.yf_prices_id_seq'::regclass);


--
-- Name: agent_health id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.agent_health ALTER COLUMN id SET DEFAULT nextval('consumption.agent_health_id_seq'::regclass);


--
-- Name: commodities id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.commodities ALTER COLUMN id SET DEFAULT nextval('consumption.commodities_id_seq'::regclass);


--
-- Name: dashboard_market_overview id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_market_overview ALTER COLUMN id SET DEFAULT nextval('consumption.dashboard_market_overview_id_seq'::regclass);


--
-- Name: dashboard_opportunities_top id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_opportunities_top ALTER COLUMN id SET DEFAULT nextval('consumption.dashboard_opportunities_top_id_seq'::regclass);


--
-- Name: dashboard_summary_cards id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_summary_cards ALTER COLUMN id SET DEFAULT nextval('consumption.dashboard_summary_cards_id_seq'::regclass);


--
-- Name: global_state id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.global_state ALTER COLUMN id SET DEFAULT nextval('consumption.global_state_id_seq'::regclass);


--
-- Name: hft_matrix id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.hft_matrix ALTER COLUMN id SET DEFAULT nextval('consumption.hft_matrix_id_seq'::regclass);


--
-- Name: markets_commodities_overview id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.markets_commodities_overview ALTER COLUMN id SET DEFAULT nextval('consumption.markets_commodities_overview_id_seq'::regclass);


--
-- Name: markets_stocks_overview id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.markets_stocks_overview ALTER COLUMN id SET DEFAULT nextval('consumption.markets_stocks_overview_id_seq'::regclass);


--
-- Name: performance_monthly_returns id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.performance_monthly_returns ALTER COLUMN id SET DEFAULT nextval('consumption.performance_monthly_returns_id_seq'::regclass);


--
-- Name: performance_strategy_attribution id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.performance_strategy_attribution ALTER COLUMN id SET DEFAULT nextval('consumption.performance_strategy_attribution_id_seq'::regclass);


--
-- Name: portfolio_positions_current id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.portfolio_positions_current ALTER COLUMN id SET DEFAULT nextval('consumption.portfolio_positions_current_id_seq'::regclass);


--
-- Name: portfolio_risk_metrics id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.portfolio_risk_metrics ALTER COLUMN id SET DEFAULT nextval('consumption.portfolio_risk_metrics_id_seq'::regclass);


--
-- Name: promoted_strategies id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.promoted_strategies ALTER COLUMN id SET DEFAULT nextval('consumption.promoted_strategies_id_seq'::regclass);


--
-- Name: research_contrarian_signals id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_contrarian_signals ALTER COLUMN id SET DEFAULT nextval('consumption.research_contrarian_signals_id_seq'::regclass);


--
-- Name: research_pipeline id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_pipeline ALTER COLUMN id SET DEFAULT nextval('consumption.research_pipeline_id_seq'::regclass);


--
-- Name: research_seasonality_patterns id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_seasonality_patterns ALTER COLUMN id SET DEFAULT nextval('consumption.research_seasonality_patterns_id_seq'::regclass);


--
-- Name: research_sue_scores id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_sue_scores ALTER COLUMN id SET DEFAULT nextval('consumption.research_sue_scores_id_seq'::regclass);


--
-- Name: settings_data_sources id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.settings_data_sources ALTER COLUMN id SET DEFAULT nextval('consumption.settings_data_sources_id_seq'::regclass);


--
-- Name: signal_logs id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.signal_logs ALTER COLUMN id SET DEFAULT nextval('consumption.signal_logs_id_seq'::regclass);


--
-- Name: strategies_backtest_results id; Type: DEFAULT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.strategies_backtest_results ALTER COLUMN id SET DEFAULT nextval('consumption.strategies_backtest_results_id_seq'::regclass);


--
-- Name: accruals_quality id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.accruals_quality ALTER COLUMN id SET DEFAULT nextval('gold.accruals_quality_id_seq'::regclass);


--
-- Name: audit_events id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.audit_events ALTER COLUMN id SET DEFAULT nextval('gold.audit_events_id_seq'::regclass);


--
-- Name: commodity_futures id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_futures ALTER COLUMN id SET DEFAULT nextval('gold.commodity_futures_id_seq'::regclass);


--
-- Name: commodity_metrics id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_metrics ALTER COLUMN id SET DEFAULT nextval('gold.commodity_metrics_id_seq'::regclass);


--
-- Name: commodity_seasonality id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_seasonality ALTER COLUMN id SET DEFAULT nextval('gold.commodity_seasonality_id_seq'::regclass);


--
-- Name: consensus_ratings id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.consensus_ratings ALTER COLUMN id SET DEFAULT nextval('gold.consensus_ratings_id_seq'::regclass);


--
-- Name: crypto_kpis id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_kpis ALTER COLUMN id SET DEFAULT nextval('gold.crypto_kpis_id_seq'::regclass);


--
-- Name: crypto_metrics id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_metrics ALTER COLUMN id SET DEFAULT nextval('gold.crypto_metrics_id_seq'::regclass);


--
-- Name: crypto_technical_metrics id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_technical_metrics ALTER COLUMN id SET DEFAULT nextval('gold.crypto_technical_metrics_id_seq'::regclass);


--
-- Name: delisted_tickers id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.delisted_tickers ALTER COLUMN id SET DEFAULT nextval('gold.delisted_tickers_id_seq'::regclass);


--
-- Name: earnings_data id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.earnings_data ALTER COLUMN id SET DEFAULT nextval('gold.earnings_data_id_seq'::regclass);


--
-- Name: earnings_signals id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.earnings_signals ALTER COLUMN id SET DEFAULT nextval('gold.earnings_signals_id_seq'::regclass);


--
-- Name: etf_daily_data id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.etf_daily_data ALTER COLUMN id SET DEFAULT nextval('gold.etf_daily_data_id_seq'::regclass);


--
-- Name: fx_alerts id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_alerts ALTER COLUMN id SET DEFAULT nextval('gold.fx_alerts_id_seq'::regclass);


--
-- Name: fx_bars_5s id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_bars_5s ALTER COLUMN id SET DEFAULT nextval('gold.fx_bars_5s_id_seq'::regclass);


--
-- Name: fx_metrics id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_metrics ALTER COLUMN id SET DEFAULT nextval('gold.fx_metrics_id_seq'::regclass);


--
-- Name: hft_metrics id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.hft_metrics ALTER COLUMN id SET DEFAULT nextval('gold.hft_metrics_id_seq'::regclass);


--
-- Name: ib_orders id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ib_orders ALTER COLUMN id SET DEFAULT nextval('gold.ib_orders_id_seq'::regclass);


--
-- Name: ibkr_orders id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ibkr_orders ALTER COLUMN id SET DEFAULT nextval('gold.ibkr_orders_id_seq'::regclass);


--
-- Name: ibkr_positions_live id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ibkr_positions_live ALTER COLUMN id SET DEFAULT nextval('gold.ibkr_positions_live_id_seq'::regclass);


--
-- Name: institutional_holdings id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.institutional_holdings ALTER COLUMN id SET DEFAULT nextval('gold.institutional_holdings_id_seq'::regclass);


--
-- Name: interbank_rates id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.interbank_rates ALTER COLUMN id SET DEFAULT nextval('gold.interbank_rates_id_seq'::regclass);


--
-- Name: llm_key_entities_config id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.llm_key_entities_config ALTER COLUMN id SET DEFAULT nextval('gold.key_entities_config_id_seq'::regclass);


--
-- Name: macro_indicators id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.macro_indicators ALTER COLUMN id SET DEFAULT nextval('gold.macro_indicators_id_seq'::regclass);


--
-- Name: market_regimes id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.market_regimes ALTER COLUMN id SET DEFAULT nextval('gold.market_regimes_id_seq'::regclass);


--
-- Name: market_sentiment_daily id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.market_sentiment_daily ALTER COLUMN id SET DEFAULT nextval('gold.market_sentiment_daily_id_seq'::regclass);


--
-- Name: metric_definitions id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.metric_definitions ALTER COLUMN id SET DEFAULT nextval('gold.metric_definitions_id_seq'::regclass);


--
-- Name: nfp_equity_drift_backtests id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.nfp_equity_drift_backtests ALTER COLUMN id SET DEFAULT nextval('gold.nfp_equity_drift_backtests_id_seq'::regclass);


--
-- Name: paper_run_log id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.paper_run_log ALTER COLUMN id SET DEFAULT nextval('gold.paper_run_log_id_seq'::regclass);


--
-- Name: paper_strategies id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.paper_strategies ALTER COLUMN id SET DEFAULT nextval('gold.paper_strategies_id_seq'::regclass);


--
-- Name: paper_trades id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.paper_trades ALTER COLUMN id SET DEFAULT nextval('gold.paper_trades_id_seq'::regclass);


--
-- Name: portfolio_snapshots id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.portfolio_snapshots ALTER COLUMN id SET DEFAULT nextval('gold.portfolio_snapshots_id_seq'::regclass);


--
-- Name: positions id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.positions ALTER COLUMN id SET DEFAULT nextval('gold.positions_id_seq'::regclass);


--
-- Name: s9_macd_signals id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.s9_macd_signals ALTER COLUMN id SET DEFAULT nextval('gold.s9_macd_signals_id_seq'::regclass);


--
-- Name: s9_paper_trades id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.s9_paper_trades ALTER COLUMN id SET DEFAULT nextval('gold.s9_paper_trades_id_seq'::regclass);


--
-- Name: seasonality_patterns id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.seasonality_patterns ALTER COLUMN id SET DEFAULT nextval('gold.seasonality_patterns_id_seq'::regclass);


--
-- Name: sector_etfs id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sector_etfs ALTER COLUMN id SET DEFAULT nextval('gold.sector_etfs_id_seq'::regclass);


--
-- Name: sentiment_mart id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sentiment_mart ALTER COLUMN id SET DEFAULT nextval('gold.sentiment_mart_id_seq'::regclass);


--
-- Name: signal_cancellations id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.signal_cancellations ALTER COLUMN id SET DEFAULT nextval('gold.signal_cancellations_id_seq'::regclass);


--
-- Name: strategy_configs id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_configs ALTER COLUMN id SET DEFAULT nextval('gold.strategy_configs_id_seq'::regclass);


--
-- Name: strategy_definitions id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_definitions ALTER COLUMN id SET DEFAULT nextval('gold.strategy_definitions_id_seq'::regclass);


--
-- Name: strategy_performance_log id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_performance_log ALTER COLUMN id SET DEFAULT nextval('gold.strategy_performance_log_id_seq'::regclass);


--
-- Name: strategy_signal_criteria id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_signal_criteria ALTER COLUMN id SET DEFAULT nextval('gold.strategy_signal_criteria_id_seq'::regclass);


--
-- Name: strategy_templates id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_templates ALTER COLUMN id SET DEFAULT nextval('gold.strategy_templates_id_seq'::regclass);


--
-- Name: strategy_thresholds id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_thresholds ALTER COLUMN id SET DEFAULT nextval('gold.strategy_thresholds_id_seq'::regclass);


--
-- Name: strategy_ticker_scores id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_ticker_scores ALTER COLUMN id SET DEFAULT nextval('gold.strategy_ticker_scores_id_seq'::regclass);


--
-- Name: strategy_universes id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_universes ALTER COLUMN id SET DEFAULT nextval('gold.strategy_universes_id_seq'::regclass);


--
-- Name: sue_scores id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sue_scores ALTER COLUMN id SET DEFAULT nextval('gold.sue_scores_id_seq'::regclass);


--
-- Name: sync_schedules id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sync_schedules ALTER COLUMN id SET DEFAULT nextval('gold.sync_schedules_id_seq'::regclass);


--
-- Name: system_config id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.system_config ALTER COLUMN id SET DEFAULT nextval('gold.system_config_id_seq'::regclass);


--
-- Name: trade_executions id; Type: DEFAULT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.trade_executions ALTER COLUMN id SET DEFAULT nextval('gold.trade_executions_id_seq'::regclass);


--
-- Name: daily_market_rca id; Type: DEFAULT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.daily_market_rca ALTER COLUMN id SET DEFAULT nextval('research_sandbox.daily_market_rca_id_seq'::regclass);


--
-- Name: daily_strategy_ideas id; Type: DEFAULT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.daily_strategy_ideas ALTER COLUMN id SET DEFAULT nextval('research_sandbox.daily_strategy_ideas_id_seq'::regclass);


--
-- Name: research_log id; Type: DEFAULT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.research_log ALTER COLUMN id SET DEFAULT nextval('research_sandbox.research_log_id_seq'::regclass);


--
-- Name: agent_tasks id; Type: DEFAULT; Schema: shared; Owner: -
--

ALTER TABLE ONLY shared.agent_tasks ALTER COLUMN id SET DEFAULT nextval('shared.agent_tasks_id_seq'::regclass);


--
-- Name: asset_registry id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.asset_registry ALTER COLUMN id SET DEFAULT nextval('silver.asset_registry_id_seq'::regclass);


--
-- Name: crypto_ohlcv_normalized id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.crypto_ohlcv_normalized ALTER COLUMN id SET DEFAULT nextval('silver.crypto_ohlcv_normalized_id_seq'::regclass);


--
-- Name: earnings_calendar id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.earnings_calendar ALTER COLUMN id SET DEFAULT nextval('silver.earnings_calendar_id_seq'::regclass);


--
-- Name: historical_news id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.historical_news ALTER COLUMN id SET DEFAULT nextval('silver.historical_news_id_seq'::regclass);


--
-- Name: historical_stock_data id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.historical_stock_data ALTER COLUMN id SET DEFAULT nextval('silver.historical_stock_data_id_seq'::regclass);


--
-- Name: market_indices id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.market_indices ALTER COLUMN id SET DEFAULT nextval('silver.market_indices_id_seq'::regclass);


--
-- Name: quarantine id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.quarantine ALTER COLUMN id SET DEFAULT nextval('silver.quarantine_id_seq'::regclass);


--
-- Name: technical_indicators id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.technical_indicators ALTER COLUMN id SET DEFAULT nextval('silver.technical_indicators_id_seq'::regclass);


--
-- Name: unified_earnings id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_earnings ALTER COLUMN id SET DEFAULT nextval('silver.unified_earnings_id_seq'::regclass);


--
-- Name: unified_ipo_calendar id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_ipo_calendar ALTER COLUMN id SET DEFAULT nextval('silver.unified_ipo_calendar_id_seq'::regclass);


--
-- Name: unified_prices id; Type: DEFAULT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_prices ALTER COLUMN id SET DEFAULT nextval('silver.unified_prices_new_id_seq'::regclass);


--
-- Name: binance_crypto_ohlcv binance_crypto_ohlcv_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.binance_crypto_ohlcv
    ADD CONSTRAINT binance_crypto_ohlcv_pkey PRIMARY KEY (id);


--
-- Name: binance_crypto_ohlcv binance_crypto_ohlcv_ticker_interval_timestamp_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.binance_crypto_ohlcv
    ADD CONSTRAINT binance_crypto_ohlcv_ticker_interval_timestamp_key UNIQUE (ticker, "interval", "timestamp");


--
-- Name: binance_funding_rates binance_funding_rates_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.binance_funding_rates
    ADD CONSTRAINT binance_funding_rates_pkey PRIMARY KEY (id);


--
-- Name: binance_funding_rates binance_funding_rates_ticker_funding_time_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.binance_funding_rates
    ADD CONSTRAINT binance_funding_rates_ticker_funding_time_key UNIQUE (ticker, funding_time);


--
-- Name: data_quality_log data_quality_log_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.data_quality_log
    ADD CONSTRAINT data_quality_log_pkey PRIMARY KEY (id);


--
-- Name: data_quality_log data_quality_log_source_table_ticker_record_date_issue_type_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.data_quality_log
    ADD CONSTRAINT data_quality_log_source_table_ticker_record_date_issue_type_key UNIQUE (source_table, ticker, record_date, issue_type);


--
-- Name: earnings_calendar earnings_calendar_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.earnings_calendar
    ADD CONSTRAINT earnings_calendar_pkey PRIMARY KEY (id);


--
-- Name: earnings_calendar earnings_calendar_ticker_earnings_date_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.earnings_calendar
    ADD CONSTRAINT earnings_calendar_ticker_earnings_date_key UNIQUE (ticker, earnings_date);


--
-- Name: fmp_institutional_holdings fmp_institutional_holdings_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.fmp_institutional_holdings
    ADD CONSTRAINT fmp_institutional_holdings_pkey PRIMARY KEY (id);


--
-- Name: fmp_institutional_holdings fmp_institutional_holdings_ticker_holder_name_report_date_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.fmp_institutional_holdings
    ADD CONSTRAINT fmp_institutional_holdings_ticker_holder_name_report_date_key UNIQUE (ticker, holder_name, report_date);


--
-- Name: fred_macro_indicators fred_macro_indicators_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.fred_macro_indicators
    ADD CONSTRAINT fred_macro_indicators_pkey PRIMARY KEY (series_id, date);


--
-- Name: fx_prices fx_prices_pair_timestamp_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.fx_prices
    ADD CONSTRAINT fx_prices_pair_timestamp_key UNIQUE (pair, "timestamp");


--
-- Name: fx_prices fx_prices_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.fx_prices
    ADD CONSTRAINT fx_prices_pkey PRIMARY KEY (id);


--
-- Name: hkex_ipo_calendar_raw hkex_ipo_calendar_raw_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.hkex_ipo_calendar_raw
    ADD CONSTRAINT hkex_ipo_calendar_raw_pkey PRIMARY KEY (id);


--
-- Name: hkex_ipo_calendar_raw hkex_ipo_calendar_raw_ticker_listing_date_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.hkex_ipo_calendar_raw
    ADD CONSTRAINT hkex_ipo_calendar_raw_ticker_listing_date_key UNIQUE (ticker, listing_date);


--
-- Name: ibkr_account_summary ibkr_account_summary_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_account_summary
    ADD CONSTRAINT ibkr_account_summary_pkey PRIMARY KEY (account);


--
-- Name: ibkr_contracts ibkr_contracts_con_id_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_contracts
    ADD CONSTRAINT ibkr_contracts_con_id_key UNIQUE (con_id);


--
-- Name: ibkr_contracts ibkr_contracts_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_contracts
    ADD CONSTRAINT ibkr_contracts_pkey PRIMARY KEY (id);


--
-- Name: ibkr_fx_bars ibkr_fx_bars_pair_bar_size_timestamp_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_fx_bars
    ADD CONSTRAINT ibkr_fx_bars_pair_bar_size_timestamp_key UNIQUE (pair, bar_size, "timestamp");


--
-- Name: ibkr_fx_bars ibkr_fx_bars_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_fx_bars
    ADD CONSTRAINT ibkr_fx_bars_pkey PRIMARY KEY (id);


--
-- Name: ibkr_fx_ticks ibkr_fx_ticks_pair_timestamp_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_fx_ticks
    ADD CONSTRAINT ibkr_fx_ticks_pair_timestamp_key UNIQUE (pair, "timestamp");


--
-- Name: ibkr_fx_ticks ibkr_fx_ticks_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_fx_ticks
    ADD CONSTRAINT ibkr_fx_ticks_pkey PRIMARY KEY (id);


--
-- Name: ibkr_historical_bars ibkr_historical_bars_con_id_bar_time_bar_size_what_to_show_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_historical_bars
    ADD CONSTRAINT ibkr_historical_bars_con_id_bar_time_bar_size_what_to_show_key UNIQUE (con_id, bar_time, bar_size, what_to_show);


--
-- Name: ibkr_historical_bars ibkr_historical_bars_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_historical_bars
    ADD CONSTRAINT ibkr_historical_bars_pkey PRIMARY KEY (id);


--
-- Name: ibkr_orders ibkr_orders_account_order_id_perm_id_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_orders
    ADD CONSTRAINT ibkr_orders_account_order_id_perm_id_key UNIQUE (account, order_id, perm_id);


--
-- Name: ibkr_orders ibkr_orders_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_orders
    ADD CONSTRAINT ibkr_orders_pkey PRIMARY KEY (id);


--
-- Name: ibkr_positions ibkr_positions_account_con_id_recorded_at_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_positions
    ADD CONSTRAINT ibkr_positions_account_con_id_recorded_at_key UNIQUE (account, con_id, recorded_at);


--
-- Name: ibkr_positions_live ibkr_positions_live_account_ticker_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_positions_live
    ADD CONSTRAINT ibkr_positions_live_account_ticker_key UNIQUE (account, ticker);


--
-- Name: ibkr_positions_live ibkr_positions_live_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_positions_live
    ADD CONSTRAINT ibkr_positions_live_pkey PRIMARY KEY (id);


--
-- Name: ibkr_positions ibkr_positions_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_positions
    ADD CONSTRAINT ibkr_positions_pkey PRIMARY KEY (id);


--
-- Name: institutional_holdings institutional_holdings_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.institutional_holdings
    ADD CONSTRAINT institutional_holdings_pkey PRIMARY KEY (id);


--
-- Name: institutional_holdings institutional_holdings_ticker_report_date_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.institutional_holdings
    ADD CONSTRAINT institutional_holdings_ticker_report_date_key UNIQUE (ticker, report_date);


--
-- Name: manual_earnings manual_earnings_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.manual_earnings
    ADD CONSTRAINT manual_earnings_pkey PRIMARY KEY (id);


--
-- Name: manual_earnings manual_earnings_ticker_report_date_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.manual_earnings
    ADD CONSTRAINT manual_earnings_ticker_report_date_key UNIQUE (ticker, report_date);


--
-- Name: nfp_consensus_proxy nfp_consensus_proxy_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.nfp_consensus_proxy
    ADD CONSTRAINT nfp_consensus_proxy_pkey PRIMARY KEY (date);


--
-- Name: raw_news raw_news_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.raw_news
    ADD CONSTRAINT raw_news_pkey PRIMARY KEY (id);


--
-- Name: raw_stock_data raw_stock_data_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.raw_stock_data
    ADD CONSTRAINT raw_stock_data_pkey PRIMARY KEY (id);


--
-- Name: yf_commodity_futures yf_commodity_futures_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.yf_commodity_futures
    ADD CONSTRAINT yf_commodity_futures_pkey PRIMARY KEY (id);


--
-- Name: yf_commodity_futures yf_commodity_futures_ticker_date_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.yf_commodity_futures
    ADD CONSTRAINT yf_commodity_futures_ticker_date_key UNIQUE (ticker, date);


--
-- Name: yf_prices yf_prices_pkey; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.yf_prices
    ADD CONSTRAINT yf_prices_pkey PRIMARY KEY (id);


--
-- Name: yf_prices yf_prices_ticker_date_key; Type: CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.yf_prices
    ADD CONSTRAINT yf_prices_ticker_date_key UNIQUE (ticker, date);


--
-- Name: agent_health agent_health_agent_id_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.agent_health
    ADD CONSTRAINT agent_health_agent_id_key UNIQUE (agent_id);


--
-- Name: agent_health agent_health_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.agent_health
    ADD CONSTRAINT agent_health_pkey PRIMARY KEY (id);


--
-- Name: commodities commodities_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.commodities
    ADD CONSTRAINT commodities_pkey PRIMARY KEY (id);


--
-- Name: cot_snapshot cot_snapshot_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.cot_snapshot
    ADD CONSTRAINT cot_snapshot_pkey PRIMARY KEY (instrument);


--
-- Name: crypto_funding_snapshot crypto_funding_snapshot_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.crypto_funding_snapshot
    ADD CONSTRAINT crypto_funding_snapshot_pkey PRIMARY KEY (symbol);


--
-- Name: dashboard_market_overview dashboard_market_overview_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_market_overview
    ADD CONSTRAINT dashboard_market_overview_pkey PRIMARY KEY (id);


--
-- Name: dashboard_market_overview dashboard_market_overview_region_index_ticker_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_market_overview
    ADD CONSTRAINT dashboard_market_overview_region_index_ticker_key UNIQUE (region, index_ticker);


--
-- Name: dashboard_opportunities_top dashboard_opportunities_top_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_opportunities_top
    ADD CONSTRAINT dashboard_opportunities_top_pkey PRIMARY KEY (id);


--
-- Name: dashboard_opportunities_top dashboard_opportunities_top_ticker_signal_type_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_opportunities_top
    ADD CONSTRAINT dashboard_opportunities_top_ticker_signal_type_key UNIQUE (ticker, signal_type);


--
-- Name: dashboard_summary_cards dashboard_summary_cards_card_key_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_summary_cards
    ADD CONSTRAINT dashboard_summary_cards_card_key_key UNIQUE (card_key);


--
-- Name: dashboard_summary_cards dashboard_summary_cards_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.dashboard_summary_cards
    ADD CONSTRAINT dashboard_summary_cards_pkey PRIMARY KEY (id);


--
-- Name: global_state global_state_key_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.global_state
    ADD CONSTRAINT global_state_key_key UNIQUE (key);


--
-- Name: global_state global_state_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.global_state
    ADD CONSTRAINT global_state_pkey PRIMARY KEY (id);


--
-- Name: hft_matrix hft_matrix_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.hft_matrix
    ADD CONSTRAINT hft_matrix_pkey PRIMARY KEY (ticker, "timestamp");


--
-- Name: hft_matrix hft_matrix_ticker_timestamp_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.hft_matrix
    ADD CONSTRAINT hft_matrix_ticker_timestamp_key UNIQUE (ticker, "timestamp");


--
-- Name: macro_calendar_dashboard macro_calendar_dashboard_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.macro_calendar_dashboard
    ADD CONSTRAINT macro_calendar_dashboard_pkey PRIMARY KEY (date);


--
-- Name: market_data_snapshot market_data_snapshot_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.market_data_snapshot
    ADD CONSTRAINT market_data_snapshot_pkey PRIMARY KEY (ticker);


--
-- Name: markets_commodities_overview markets_commodities_overview_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.markets_commodities_overview
    ADD CONSTRAINT markets_commodities_overview_pkey PRIMARY KEY (id);


--
-- Name: markets_commodities_overview markets_commodities_overview_ticker_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.markets_commodities_overview
    ADD CONSTRAINT markets_commodities_overview_ticker_key UNIQUE (ticker);


--
-- Name: markets_stocks_overview markets_stocks_overview_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.markets_stocks_overview
    ADD CONSTRAINT markets_stocks_overview_pkey PRIMARY KEY (id);


--
-- Name: markets_stocks_overview markets_stocks_overview_ticker_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.markets_stocks_overview
    ADD CONSTRAINT markets_stocks_overview_ticker_key UNIQUE (ticker);


--
-- Name: performance_monthly_returns performance_monthly_returns_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.performance_monthly_returns
    ADD CONSTRAINT performance_monthly_returns_pkey PRIMARY KEY (id);


--
-- Name: performance_monthly_returns performance_monthly_returns_portfolio_type_year_month_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.performance_monthly_returns
    ADD CONSTRAINT performance_monthly_returns_portfolio_type_year_month_key UNIQUE (portfolio_type, year, month);


--
-- Name: performance_strategy_attribution performance_strategy_attribution_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.performance_strategy_attribution
    ADD CONSTRAINT performance_strategy_attribution_pkey PRIMARY KEY (id);


--
-- Name: performance_strategy_attribution performance_strategy_attribution_strategy_id_portfolio_type_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.performance_strategy_attribution
    ADD CONSTRAINT performance_strategy_attribution_strategy_id_portfolio_type_key UNIQUE (strategy_id, portfolio_type);


--
-- Name: portfolio_positions_current portfolio_positions_current_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.portfolio_positions_current
    ADD CONSTRAINT portfolio_positions_current_pkey PRIMARY KEY (id);


--
-- Name: portfolio_positions_current portfolio_positions_current_ticker_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.portfolio_positions_current
    ADD CONSTRAINT portfolio_positions_current_ticker_key UNIQUE (ticker);


--
-- Name: portfolio_risk_metrics portfolio_risk_metrics_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.portfolio_risk_metrics
    ADD CONSTRAINT portfolio_risk_metrics_pkey PRIMARY KEY (id);


--
-- Name: portfolio_risk_metrics portfolio_risk_metrics_portfolio_type_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.portfolio_risk_metrics
    ADD CONSTRAINT portfolio_risk_metrics_portfolio_type_key UNIQUE (portfolio_type);


--
-- Name: promoted_strategies promoted_strategies_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.promoted_strategies
    ADD CONSTRAINT promoted_strategies_pkey PRIMARY KEY (id);


--
-- Name: promoted_strategies promoted_strategies_strategy_id_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.promoted_strategies
    ADD CONSTRAINT promoted_strategies_strategy_id_key UNIQUE (strategy_id);


--
-- Name: research_contrarian_signals research_contrarian_signals_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_contrarian_signals
    ADD CONSTRAINT research_contrarian_signals_pkey PRIMARY KEY (id);


--
-- Name: research_contrarian_signals research_contrarian_signals_ticker_signal_type_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_contrarian_signals
    ADD CONSTRAINT research_contrarian_signals_ticker_signal_type_key UNIQUE (ticker, signal_type);


--
-- Name: research_pipeline research_pipeline_experiment_id_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_pipeline
    ADD CONSTRAINT research_pipeline_experiment_id_key UNIQUE (experiment_id);


--
-- Name: research_pipeline research_pipeline_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_pipeline
    ADD CONSTRAINT research_pipeline_pkey PRIMARY KEY (id);


--
-- Name: research_seasonality_patterns research_seasonality_patterns_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_seasonality_patterns
    ADD CONSTRAINT research_seasonality_patterns_pkey PRIMARY KEY (id);


--
-- Name: research_seasonality_patterns research_seasonality_patterns_ticker_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_seasonality_patterns
    ADD CONSTRAINT research_seasonality_patterns_ticker_key UNIQUE (ticker);


--
-- Name: research_sue_scores research_sue_scores_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_sue_scores
    ADD CONSTRAINT research_sue_scores_pkey PRIMARY KEY (id);


--
-- Name: research_sue_scores research_sue_scores_ticker_report_date_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.research_sue_scores
    ADD CONSTRAINT research_sue_scores_ticker_report_date_key UNIQUE (ticker, report_date);


--
-- Name: settings_data_sources settings_data_sources_data_type_source_priority_key; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.settings_data_sources
    ADD CONSTRAINT settings_data_sources_data_type_source_priority_key UNIQUE (data_type, source_priority);


--
-- Name: settings_data_sources settings_data_sources_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.settings_data_sources
    ADD CONSTRAINT settings_data_sources_pkey PRIMARY KEY (id);


--
-- Name: signal_logs signal_logs_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.signal_logs
    ADD CONSTRAINT signal_logs_pkey PRIMARY KEY (id);


--
-- Name: strategies_backtest_results strategies_backtest_results_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.strategies_backtest_results
    ADD CONSTRAINT strategies_backtest_results_pkey PRIMARY KEY (id);


--
-- Name: strategy_scores_dynamic strategy_scores_dynamic_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.strategy_scores_dynamic
    ADD CONSTRAINT strategy_scores_dynamic_pkey PRIMARY KEY (strategy_id, ticker);


--
-- Name: ticker_scores ticker_scores_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.ticker_scores
    ADD CONSTRAINT ticker_scores_pkey PRIMARY KEY (ticker, strategy_id);


--
-- Name: vix_dashboard vix_dashboard_pkey; Type: CONSTRAINT; Schema: consumption; Owner: -
--

ALTER TABLE ONLY consumption.vix_dashboard
    ADD CONSTRAINT vix_dashboard_pkey PRIMARY KEY (date);


--
-- Name: accruals_quality accruals_quality_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.accruals_quality
    ADD CONSTRAINT accruals_quality_pkey PRIMARY KEY (id);


--
-- Name: accruals_quality accruals_quality_ticker_quarter_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.accruals_quality
    ADD CONSTRAINT accruals_quality_ticker_quarter_key UNIQUE (ticker, quarter);


--
-- Name: agent_events agent_events_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.agent_events
    ADD CONSTRAINT agent_events_pkey PRIMARY KEY (id);


--
-- Name: asset_registry asset_registry_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.asset_registry
    ADD CONSTRAINT asset_registry_pkey PRIMARY KEY (ticker);


--
-- Name: audit_events audit_events_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (id);


--
-- Name: commodity_futures commodity_futures_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_futures
    ADD CONSTRAINT commodity_futures_pkey PRIMARY KEY (id);


--
-- Name: commodity_futures commodity_futures_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_futures
    ADD CONSTRAINT commodity_futures_ticker_date_key UNIQUE (ticker, date);


--
-- Name: commodity_metrics commodity_metrics_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_metrics
    ADD CONSTRAINT commodity_metrics_pkey PRIMARY KEY (id);


--
-- Name: commodity_metrics commodity_metrics_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_metrics
    ADD CONSTRAINT commodity_metrics_ticker_date_key UNIQUE (ticker, date);


--
-- Name: commodity_seasonality commodity_seasonality_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_seasonality
    ADD CONSTRAINT commodity_seasonality_pkey PRIMARY KEY (id);


--
-- Name: commodity_seasonality commodity_seasonality_ticker_month_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.commodity_seasonality
    ADD CONSTRAINT commodity_seasonality_ticker_month_key UNIQUE (ticker, month);


--
-- Name: consensus_ratings consensus_ratings_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.consensus_ratings
    ADD CONSTRAINT consensus_ratings_pkey PRIMARY KEY (id);


--
-- Name: consensus_ratings consensus_ratings_ticker_report_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.consensus_ratings
    ADD CONSTRAINT consensus_ratings_ticker_report_date_key UNIQUE (ticker, report_date);


--
-- Name: cot_sentiment cot_sentiment_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.cot_sentiment
    ADD CONSTRAINT cot_sentiment_pkey PRIMARY KEY (instrument, date);


--
-- Name: crypto_funding_metrics crypto_funding_metrics_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_funding_metrics
    ADD CONSTRAINT crypto_funding_metrics_pkey PRIMARY KEY (symbol, date);


--
-- Name: crypto_kpis crypto_kpis_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_kpis
    ADD CONSTRAINT crypto_kpis_pkey PRIMARY KEY (id);


--
-- Name: crypto_kpis crypto_kpis_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_kpis
    ADD CONSTRAINT crypto_kpis_ticker_date_key UNIQUE (ticker, date);


--
-- Name: crypto_metrics crypto_metrics_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_metrics
    ADD CONSTRAINT crypto_metrics_pkey PRIMARY KEY (id);


--
-- Name: crypto_metrics crypto_metrics_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_metrics
    ADD CONSTRAINT crypto_metrics_ticker_date_key UNIQUE (ticker, date);


--
-- Name: crypto_technical_metrics crypto_technical_metrics_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_technical_metrics
    ADD CONSTRAINT crypto_technical_metrics_pkey PRIMARY KEY (id);


--
-- Name: crypto_technical_metrics crypto_technical_metrics_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.crypto_technical_metrics
    ADD CONSTRAINT crypto_technical_metrics_ticker_date_key UNIQUE (ticker, date);


--
-- Name: daily_ohlcv daily_ohlcv_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.daily_ohlcv
    ADD CONSTRAINT daily_ohlcv_pkey PRIMARY KEY (ticker, date);


--
-- Name: delisted_tickers delisted_tickers_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.delisted_tickers
    ADD CONSTRAINT delisted_tickers_pkey PRIMARY KEY (id);


--
-- Name: delisted_tickers delisted_tickers_ticker_delisted_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.delisted_tickers
    ADD CONSTRAINT delisted_tickers_ticker_delisted_date_key UNIQUE (ticker, delisted_date);


--
-- Name: earnings_data earnings_data_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.earnings_data
    ADD CONSTRAINT earnings_data_pkey PRIMARY KEY (id);


--
-- Name: earnings_data earnings_data_ticker_report_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.earnings_data
    ADD CONSTRAINT earnings_data_ticker_report_date_key UNIQUE (ticker, report_date);


--
-- Name: earnings_signals earnings_signals_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.earnings_signals
    ADD CONSTRAINT earnings_signals_pkey PRIMARY KEY (id);


--
-- Name: earnings_signals earnings_signals_symbol_earnings_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.earnings_signals
    ADD CONSTRAINT earnings_signals_symbol_earnings_date_key UNIQUE (symbol, earnings_date);


--
-- Name: kpis_metrics equities_kpis_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.kpis_metrics
    ADD CONSTRAINT equities_kpis_pkey PRIMARY KEY (ticker, date);


--
-- Name: etf_daily_data etf_daily_data_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.etf_daily_data
    ADD CONSTRAINT etf_daily_data_pkey PRIMARY KEY (id);


--
-- Name: etf_daily_data etf_daily_data_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.etf_daily_data
    ADD CONSTRAINT etf_daily_data_ticker_date_key UNIQUE (ticker, date);


--
-- Name: fx_alerts fx_alerts_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_alerts
    ADD CONSTRAINT fx_alerts_pkey PRIMARY KEY (id);


--
-- Name: fx_bars_5s fx_bars_5s_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_bars_5s
    ADD CONSTRAINT fx_bars_5s_pkey PRIMARY KEY (id);


--
-- Name: fx_bars_5s fx_bars_5s_timestamp_ticker_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_bars_5s
    ADD CONSTRAINT fx_bars_5s_timestamp_ticker_key UNIQUE ("timestamp", ticker);


--
-- Name: fx_metrics fx_metrics_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_metrics
    ADD CONSTRAINT fx_metrics_pkey PRIMARY KEY (id);


--
-- Name: fx_metrics fx_metrics_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.fx_metrics
    ADD CONSTRAINT fx_metrics_ticker_date_key UNIQUE (ticker, date);


--
-- Name: hft_metrics hft_metrics_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.hft_metrics
    ADD CONSTRAINT hft_metrics_pkey PRIMARY KEY (id);


--
-- Name: hft_metrics hft_metrics_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.hft_metrics
    ADD CONSTRAINT hft_metrics_ticker_date_key UNIQUE (ticker, date);


--
-- Name: hk_ipo_calendar hk_ipo_calendar_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.hk_ipo_calendar
    ADD CONSTRAINT hk_ipo_calendar_pkey PRIMARY KEY (ticker);


--
-- Name: hk_ipo_details hk_ipo_details_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.hk_ipo_details
    ADD CONSTRAINT hk_ipo_details_pkey PRIMARY KEY (ticker);


--
-- Name: hk_ipo_performance hk_ipo_performance_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.hk_ipo_performance
    ADD CONSTRAINT hk_ipo_performance_pkey PRIMARY KEY (ticker);


--
-- Name: hmm_regime_states hmm_regime_states_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.hmm_regime_states
    ADD CONSTRAINT hmm_regime_states_pkey PRIMARY KEY (date);


--
-- Name: ib_orders ib_orders_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ib_orders
    ADD CONSTRAINT ib_orders_pkey PRIMARY KEY (id);


--
-- Name: ibkr_account_summary ibkr_account_summary_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ibkr_account_summary
    ADD CONSTRAINT ibkr_account_summary_pkey PRIMARY KEY (account);


--
-- Name: ibkr_orders ibkr_orders_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ibkr_orders
    ADD CONSTRAINT ibkr_orders_pkey PRIMARY KEY (id);


--
-- Name: ibkr_positions_live ibkr_positions_live_account_ticker_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ibkr_positions_live
    ADD CONSTRAINT ibkr_positions_live_account_ticker_key UNIQUE (account, ticker);


--
-- Name: ibkr_positions_live ibkr_positions_live_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ibkr_positions_live
    ADD CONSTRAINT ibkr_positions_live_pkey PRIMARY KEY (id);


--
-- Name: index_metrics index_metrics_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.index_metrics
    ADD CONSTRAINT index_metrics_pkey PRIMARY KEY (date, ticker);


--
-- Name: institutional_holdings institutional_holdings_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.institutional_holdings
    ADD CONSTRAINT institutional_holdings_pkey PRIMARY KEY (id);


--
-- Name: institutional_holdings institutional_holdings_ticker_holder_name_report_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.institutional_holdings
    ADD CONSTRAINT institutional_holdings_ticker_holder_name_report_date_key UNIQUE (ticker, holder_name, report_date);


--
-- Name: interbank_rates interbank_rates_date_currency_tenor_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.interbank_rates
    ADD CONSTRAINT interbank_rates_date_currency_tenor_key UNIQUE (date, currency, tenor);


--
-- Name: interbank_rates interbank_rates_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.interbank_rates
    ADD CONSTRAINT interbank_rates_pkey PRIMARY KEY (id);


--
-- Name: llm_key_entities_config key_entities_config_name_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.llm_key_entities_config
    ADD CONSTRAINT key_entities_config_name_key UNIQUE (name);


--
-- Name: llm_key_entities_config key_entities_config_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.llm_key_entities_config
    ADD CONSTRAINT key_entities_config_pkey PRIMARY KEY (id);


--
-- Name: macro_event_flags macro_event_flags_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.macro_event_flags
    ADD CONSTRAINT macro_event_flags_pkey PRIMARY KEY (date);


--
-- Name: macro_indicators macro_indicators_date_indicator_name_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.macro_indicators
    ADD CONSTRAINT macro_indicators_date_indicator_name_key UNIQUE (date, indicator_name);


--
-- Name: macro_indicators macro_indicators_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.macro_indicators
    ADD CONSTRAINT macro_indicators_pkey PRIMARY KEY (id);


--
-- Name: market_regimes market_regimes_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.market_regimes
    ADD CONSTRAINT market_regimes_pkey PRIMARY KEY (id);


--
-- Name: market_sentiment_daily market_sentiment_daily_market_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.market_sentiment_daily
    ADD CONSTRAINT market_sentiment_daily_market_date_key UNIQUE (market, date);


--
-- Name: market_sentiment_daily market_sentiment_daily_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.market_sentiment_daily
    ADD CONSTRAINT market_sentiment_daily_pkey PRIMARY KEY (id);


--
-- Name: metric_definitions metric_definitions_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.metric_definitions
    ADD CONSTRAINT metric_definitions_pkey PRIMARY KEY (id);


--
-- Name: nfp_equity_drift_backtests nfp_equity_drift_backtests_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.nfp_equity_drift_backtests
    ADD CONSTRAINT nfp_equity_drift_backtests_pkey PRIMARY KEY (id);


--
-- Name: nfp_equity_drift_backtests nfp_equity_drift_backtests_strategy_name_version_backtest_d_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.nfp_equity_drift_backtests
    ADD CONSTRAINT nfp_equity_drift_backtests_strategy_name_version_backtest_d_key UNIQUE (strategy_name, version, backtest_date);


--
-- Name: paper_run_log paper_run_log_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.paper_run_log
    ADD CONSTRAINT paper_run_log_pkey PRIMARY KEY (id);


--
-- Name: paper_strategies paper_strategies_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.paper_strategies
    ADD CONSTRAINT paper_strategies_pkey PRIMARY KEY (id);


--
-- Name: paper_strategies paper_strategies_strategy_id_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.paper_strategies
    ADD CONSTRAINT paper_strategies_strategy_id_key UNIQUE (strategy_id);


--
-- Name: paper_trades paper_trades_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.paper_trades
    ADD CONSTRAINT paper_trades_pkey PRIMARY KEY (id);


--
-- Name: platform_settings platform_settings_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.platform_settings
    ADD CONSTRAINT platform_settings_pkey PRIMARY KEY (key);


--
-- Name: portfolio_snapshots portfolio_snapshots_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.portfolio_snapshots
    ADD CONSTRAINT portfolio_snapshots_pkey PRIMARY KEY (id);


--
-- Name: portfolio_snapshots portfolio_snapshots_snapshot_date_portfolio_type_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.portfolio_snapshots
    ADD CONSTRAINT portfolio_snapshots_snapshot_date_portfolio_type_key UNIQUE (snapshot_date, portfolio_type);


--
-- Name: positions positions_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.positions
    ADD CONSTRAINT positions_pkey PRIMARY KEY (id);


--
-- Name: regime_features regime_features_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.regime_features
    ADD CONSTRAINT regime_features_pkey PRIMARY KEY (date);


--
-- Name: regime_label regime_label_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.regime_label
    ADD CONSTRAINT regime_label_pkey PRIMARY KEY (date);


--
-- Name: s9_macd_signals s9_macd_signals_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.s9_macd_signals
    ADD CONSTRAINT s9_macd_signals_pkey PRIMARY KEY (id);


--
-- Name: s9_macd_signals s9_macd_signals_strategy_id_ticker_signal_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.s9_macd_signals
    ADD CONSTRAINT s9_macd_signals_strategy_id_ticker_signal_date_key UNIQUE (strategy_id, ticker, signal_date);


--
-- Name: s9_paper_trades s9_paper_trades_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.s9_paper_trades
    ADD CONSTRAINT s9_paper_trades_pkey PRIMARY KEY (id);


--
-- Name: seasonality_patterns seasonality_patterns_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.seasonality_patterns
    ADD CONSTRAINT seasonality_patterns_pkey PRIMARY KEY (id);


--
-- Name: seasonality_patterns seasonality_patterns_ticker_month_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.seasonality_patterns
    ADD CONSTRAINT seasonality_patterns_ticker_month_key UNIQUE (ticker, month);


--
-- Name: sector_etfs sector_etfs_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sector_etfs
    ADD CONSTRAINT sector_etfs_pkey PRIMARY KEY (id);


--
-- Name: sector_etfs sector_etfs_ticker_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sector_etfs
    ADD CONSTRAINT sector_etfs_ticker_date_key UNIQUE (ticker, date);


--
-- Name: sentiment_mart sentiment_mart_date_entity_name_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sentiment_mart
    ADD CONSTRAINT sentiment_mart_date_entity_name_key UNIQUE (date, entity_name);


--
-- Name: sentiment_mart sentiment_mart_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sentiment_mart
    ADD CONSTRAINT sentiment_mart_pkey PRIMARY KEY (id);


--
-- Name: signal_cancellations signal_cancellations_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.signal_cancellations
    ADD CONSTRAINT signal_cancellations_pkey PRIMARY KEY (id);


--
-- Name: stock_metrics_history stock_metrics_history_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.stock_metrics_history
    ADD CONSTRAINT stock_metrics_history_pkey PRIMARY KEY (date, ticker);


--
-- Name: stock_metrics_new stock_metrics_new_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.stock_metrics_new
    ADD CONSTRAINT stock_metrics_new_pkey PRIMARY KEY (ticker, date);


--
-- Name: strategy_backtest_runs strategy_backtest_runs_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_backtest_runs
    ADD CONSTRAINT strategy_backtest_runs_pkey PRIMARY KEY (run_id);


--
-- Name: strategy_backtest_trades strategy_backtest_trades_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_backtest_trades
    ADD CONSTRAINT strategy_backtest_trades_pkey PRIMARY KEY (trade_id);


--
-- Name: strategy_backtests strategy_backtests_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_backtests
    ADD CONSTRAINT strategy_backtests_pkey PRIMARY KEY (strategy_id, run_date);


--
-- Name: strategy_configs strategy_configs_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_configs
    ADD CONSTRAINT strategy_configs_pkey PRIMARY KEY (id);


--
-- Name: strategy_configs strategy_configs_strategy_id_config_key_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_configs
    ADD CONSTRAINT strategy_configs_strategy_id_config_key_key UNIQUE (strategy_id, config_key);


--
-- Name: strategy_definitions strategy_definitions_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_definitions
    ADD CONSTRAINT strategy_definitions_pkey PRIMARY KEY (id);


--
-- Name: strategy_definitions strategy_definitions_strategy_id_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_definitions
    ADD CONSTRAINT strategy_definitions_strategy_id_key UNIQUE (strategy_id);


--
-- Name: strategy_performance_log strategy_performance_log_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_performance_log
    ADD CONSTRAINT strategy_performance_log_pkey PRIMARY KEY (id);


--
-- Name: strategy_performance_log strategy_performance_log_strategy_id_log_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_performance_log
    ADD CONSTRAINT strategy_performance_log_strategy_id_log_date_key UNIQUE (strategy_id, log_date);


--
-- Name: strategy_qa_reviews strategy_qa_reviews_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_qa_reviews
    ADD CONSTRAINT strategy_qa_reviews_pkey PRIMARY KEY (review_id);


--
-- Name: strategy_registry strategy_registry_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_registry
    ADD CONSTRAINT strategy_registry_pkey PRIMARY KEY (strategy_id);


--
-- Name: strategy_research strategy_research_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_research
    ADD CONSTRAINT strategy_research_pkey PRIMARY KEY (strategy_id);


--
-- Name: strategy_risk_reviews strategy_risk_reviews_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_risk_reviews
    ADD CONSTRAINT strategy_risk_reviews_pkey PRIMARY KEY (review_id);


--
-- Name: strategy_signal_criteria strategy_signal_criteria_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_signal_criteria
    ADD CONSTRAINT strategy_signal_criteria_pkey PRIMARY KEY (id);


--
-- Name: strategy_signal_criteria strategy_signal_criteria_strategy_id_signal_type_criterion__key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_signal_criteria
    ADD CONSTRAINT strategy_signal_criteria_strategy_id_signal_type_criterion__key UNIQUE (strategy_id, signal_type, criterion_name);


--
-- Name: strategy_signals strategy_signals_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_signals
    ADD CONSTRAINT strategy_signals_pkey PRIMARY KEY (date, strategy_id);


--
-- Name: strategy_templates strategy_templates_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_templates
    ADD CONSTRAINT strategy_templates_pkey PRIMARY KEY (id);


--
-- Name: strategy_templates strategy_templates_template_id_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_templates
    ADD CONSTRAINT strategy_templates_template_id_key UNIQUE (template_id);


--
-- Name: strategy_thresholds strategy_thresholds_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_thresholds
    ADD CONSTRAINT strategy_thresholds_pkey PRIMARY KEY (id);


--
-- Name: strategy_ticker_scores strategy_ticker_scores_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_ticker_scores
    ADD CONSTRAINT strategy_ticker_scores_pkey PRIMARY KEY (id);


--
-- Name: strategy_ticker_scores strategy_ticker_scores_strategy_id_ticker_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_ticker_scores
    ADD CONSTRAINT strategy_ticker_scores_strategy_id_ticker_key UNIQUE (strategy_id, ticker);


--
-- Name: strategy_universes strategy_universes_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_universes
    ADD CONSTRAINT strategy_universes_pkey PRIMARY KEY (id);


--
-- Name: strategy_universes strategy_universes_strategy_id_ticker_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_universes
    ADD CONSTRAINT strategy_universes_strategy_id_ticker_key UNIQUE (strategy_id, ticker);


--
-- Name: sue_scores sue_scores_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sue_scores
    ADD CONSTRAINT sue_scores_pkey PRIMARY KEY (id);


--
-- Name: sue_scores sue_scores_ticker_report_date_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sue_scores
    ADD CONSTRAINT sue_scores_ticker_report_date_key UNIQUE (ticker, report_date);


--
-- Name: sync_schedules sync_schedules_component_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sync_schedules
    ADD CONSTRAINT sync_schedules_component_key UNIQUE (component);


--
-- Name: sync_schedules sync_schedules_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.sync_schedules
    ADD CONSTRAINT sync_schedules_pkey PRIMARY KEY (id);


--
-- Name: system_config system_config_component_key_key; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.system_config
    ADD CONSTRAINT system_config_component_key_key UNIQUE (component, key);


--
-- Name: system_config system_config_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.system_config
    ADD CONSTRAINT system_config_pkey PRIMARY KEY (id);


--
-- Name: trade_executions trade_executions_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.trade_executions
    ADD CONSTRAINT trade_executions_pkey PRIMARY KEY (id);


--
-- Name: ibkr_orders uk_ibkr_orders_account_order_id; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.ibkr_orders
    ADD CONSTRAINT uk_ibkr_orders_account_order_id UNIQUE (account, order_id);


--
-- Name: vix_regime vix_regime_pkey; Type: CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.vix_regime
    ADD CONSTRAINT vix_regime_pkey PRIMARY KEY (date);


--
-- Name: gold_layer_state gold_layer_state_pkey; Type: CONSTRAINT; Schema: openclaw_researcher; Owner: -
--

ALTER TABLE ONLY openclaw_researcher.gold_layer_state
    ADD CONSTRAINT gold_layer_state_pkey PRIMARY KEY (id);


--
-- Name: benchmark_indices benchmark_indices_pkey; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.benchmark_indices
    ADD CONSTRAINT benchmark_indices_pkey PRIMARY KEY (date, ticker);


--
-- Name: daily_market_rca daily_market_rca_date_market_ticker_key; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.daily_market_rca
    ADD CONSTRAINT daily_market_rca_date_market_ticker_key UNIQUE (date, market, ticker);


--
-- Name: daily_market_rca daily_market_rca_pkey; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.daily_market_rca
    ADD CONSTRAINT daily_market_rca_pkey PRIMARY KEY (id);


--
-- Name: daily_strategy_ideas daily_strategy_ideas_pkey; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.daily_strategy_ideas
    ADD CONSTRAINT daily_strategy_ideas_pkey PRIMARY KEY (id);


--
-- Name: research_log research_log_pkey; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.research_log
    ADD CONSTRAINT research_log_pkey PRIMARY KEY (id);


--
-- Name: spy_ohlcv spy_ohlcv_pkey; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.spy_ohlcv
    ADD CONSTRAINT spy_ohlcv_pkey PRIMARY KEY (date);


--
-- Name: ticker_sectors ticker_sectors_pkey; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.ticker_sectors
    ADD CONSTRAINT ticker_sectors_pkey PRIMARY KEY (ticker);


--
-- Name: vix_data vix_data_pkey; Type: CONSTRAINT; Schema: research_sandbox; Owner: -
--

ALTER TABLE ONLY research_sandbox.vix_data
    ADD CONSTRAINT vix_data_pkey PRIMARY KEY (date);


--
-- Name: agent_tasks agent_tasks_pkey; Type: CONSTRAINT; Schema: shared; Owner: -
--

ALTER TABLE ONLY shared.agent_tasks
    ADD CONSTRAINT agent_tasks_pkey PRIMARY KEY (id);


--
-- Name: asset_registry asset_registry_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.asset_registry
    ADD CONSTRAINT asset_registry_pkey PRIMARY KEY (id);


--
-- Name: asset_registry asset_registry_ticker_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.asset_registry
    ADD CONSTRAINT asset_registry_ticker_key UNIQUE (ticker);


--
-- Name: cot_euro_fx_daily cot_euro_fx_daily_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.cot_euro_fx_daily
    ADD CONSTRAINT cot_euro_fx_daily_pkey PRIMARY KEY (instrument, date);


--
-- Name: crypto_ohlcv_normalized crypto_ohlcv_normalized_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.crypto_ohlcv_normalized
    ADD CONSTRAINT crypto_ohlcv_normalized_pkey PRIMARY KEY (id);


--
-- Name: crypto_ohlcv_normalized crypto_ohlcv_normalized_symbol_interval_timestamp_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.crypto_ohlcv_normalized
    ADD CONSTRAINT crypto_ohlcv_normalized_symbol_interval_timestamp_key UNIQUE (symbol, "interval", "timestamp");


--
-- Name: earnings_calendar earnings_calendar_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.earnings_calendar
    ADD CONSTRAINT earnings_calendar_pkey PRIMARY KEY (id);


--
-- Name: earnings_calendar earnings_calendar_report_date_ticker_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.earnings_calendar
    ADD CONSTRAINT earnings_calendar_report_date_ticker_key UNIQUE (report_date, ticker);


--
-- Name: funding_rates_daily funding_rates_daily_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.funding_rates_daily
    ADD CONSTRAINT funding_rates_daily_pkey PRIMARY KEY (symbol, date);


--
-- Name: historical_news historical_news_date_entity_name_headline_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.historical_news
    ADD CONSTRAINT historical_news_date_entity_name_headline_key UNIQUE (date, entity_name, headline);


--
-- Name: historical_news historical_news_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.historical_news
    ADD CONSTRAINT historical_news_pkey PRIMARY KEY (id);


--
-- Name: historical_stock_data historical_stock_data_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.historical_stock_data
    ADD CONSTRAINT historical_stock_data_pkey PRIMARY KEY (id);


--
-- Name: historical_stock_data historical_stock_data_ticker_date_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.historical_stock_data
    ADD CONSTRAINT historical_stock_data_ticker_date_key UNIQUE (ticker, date);


--
-- Name: macro_event_calendar macro_event_calendar_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.macro_event_calendar
    ADD CONSTRAINT macro_event_calendar_pkey PRIMARY KEY (date);


--
-- Name: market_indices market_indices_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.market_indices
    ADD CONSTRAINT market_indices_pkey PRIMARY KEY (id);


--
-- Name: market_indices market_indices_ticker_date_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.market_indices
    ADD CONSTRAINT market_indices_ticker_date_key UNIQUE (ticker, date);


--
-- Name: quarantine quarantine_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.quarantine
    ADD CONSTRAINT quarantine_pkey PRIMARY KEY (id);


--
-- Name: technical_indicators technical_indicators_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.technical_indicators
    ADD CONSTRAINT technical_indicators_pkey PRIMARY KEY (id);


--
-- Name: technical_indicators technical_indicators_ticker_date_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.technical_indicators
    ADD CONSTRAINT technical_indicators_ticker_date_key UNIQUE (ticker, date);


--
-- Name: unified_earnings unified_earnings_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_earnings
    ADD CONSTRAINT unified_earnings_pkey PRIMARY KEY (id);


--
-- Name: unified_earnings unified_earnings_ticker_report_date_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_earnings
    ADD CONSTRAINT unified_earnings_ticker_report_date_key UNIQUE (ticker, report_date);


--
-- Name: unified_ipo_calendar unified_ipo_calendar_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_ipo_calendar
    ADD CONSTRAINT unified_ipo_calendar_pkey PRIMARY KEY (id);


--
-- Name: unified_ipo_calendar unified_ipo_calendar_ticker_listing_date_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_ipo_calendar
    ADD CONSTRAINT unified_ipo_calendar_ticker_listing_date_key UNIQUE (ticker, listing_date);


--
-- Name: unified_ipo_performance unified_ipo_performance_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_ipo_performance
    ADD CONSTRAINT unified_ipo_performance_pkey PRIMARY KEY (ticker);


--
-- Name: unified_prices unified_prices_new_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_prices
    ADD CONSTRAINT unified_prices_new_pkey PRIMARY KEY (id);


--
-- Name: unified_prices unified_prices_new_ticker_date_key; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.unified_prices
    ADD CONSTRAINT unified_prices_new_ticker_date_key UNIQUE (ticker, date);


--
-- Name: vix_indicators vix_indicators_pkey; Type: CONSTRAINT; Schema: silver; Owner: -
--

ALTER TABLE ONLY silver.vix_indicators
    ADD CONSTRAINT vix_indicators_pkey PRIMARY KEY (ticker, date);


--
-- Name: idx_dql_source; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_dql_source ON bronze.data_quality_log USING btree (source_table, logged_at DESC);


--
-- Name: idx_ec_date; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_ec_date ON bronze.earnings_calendar USING btree (earnings_date DESC);


--
-- Name: idx_ec_ticker; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_ec_ticker ON bronze.earnings_calendar USING btree (ticker, earnings_date DESC);


--
-- Name: idx_ibkr_orders_account; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_ibkr_orders_account ON bronze.ibkr_orders USING btree (account);


--
-- Name: idx_ibkr_orders_fetched_at; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_ibkr_orders_fetched_at ON bronze.ibkr_orders USING btree (fetched_at);


--
-- Name: idx_ibkr_orders_status; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_ibkr_orders_status ON bronze.ibkr_orders USING btree (status);


--
-- Name: idx_ibkr_orders_ticker; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_ibkr_orders_ticker ON bronze.ibkr_orders USING btree (ticker);


--
-- Name: idx_ih_date; Type: INDEX; Schema: bronze; Owner: -
--

CREATE INDEX idx_ih_date ON bronze.institutional_holdings USING btree (report_date DESC);


--
-- Name: idx_commodities_timestamp; Type: INDEX; Schema: consumption; Owner: -
--

CREATE INDEX idx_commodities_timestamp ON consumption.commodities USING btree ("timestamp");


--
-- Name: idx_rp_updated; Type: INDEX; Schema: consumption; Owner: -
--

CREATE INDEX idx_rp_updated ON consumption.research_pipeline USING btree (updated_at DESC);


--
-- Name: idx_scores_updated; Type: INDEX; Schema: consumption; Owner: -
--

CREATE INDEX idx_scores_updated ON consumption.strategy_scores_dynamic USING btree (last_updated DESC);


--
-- Name: idx_agent_events_created; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_agent_events_created ON gold.agent_events USING btree (created_at DESC);


--
-- Name: idx_agent_events_source; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_agent_events_source ON gold.agent_events USING btree (agent_name);


--
-- Name: idx_agent_events_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_agent_events_strategy ON gold.agent_events USING btree (strategy_id);


--
-- Name: idx_commodity_futures_ticker_date_desc; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_commodity_futures_ticker_date_desc ON gold.commodity_futures USING btree (ticker, date DESC);


--
-- Name: idx_earnings_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_earnings_date ON gold.earnings_data USING btree (report_date DESC);


--
-- Name: idx_earnings_ticker; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_earnings_ticker ON gold.earnings_data USING btree (ticker);


--
-- Name: idx_equities_kpis_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_equities_kpis_date ON gold.kpis_metrics USING btree (date);


--
-- Name: idx_equities_kpis_ticker; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_equities_kpis_ticker ON gold.kpis_metrics USING btree (ticker);


--
-- Name: idx_futures_category; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_futures_category ON gold.commodity_futures USING btree (category);


--
-- Name: idx_futures_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_futures_date ON gold.commodity_futures USING btree (date DESC);


--
-- Name: idx_futures_ticker; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_futures_ticker ON gold.commodity_futures USING btree (ticker);


--
-- Name: idx_gold_cot_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_gold_cot_date ON gold.cot_sentiment USING btree (date DESC);


--
-- Name: idx_gold_crypto_funding_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_gold_crypto_funding_date ON gold.crypto_funding_metrics USING btree (date DESC);


--
-- Name: idx_gold_daily_ohlcv_asset; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_gold_daily_ohlcv_asset ON gold.daily_ohlcv USING btree (asset_class, date DESC);


--
-- Name: idx_gold_daily_ohlcv_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_gold_daily_ohlcv_date ON gold.daily_ohlcv USING btree (date DESC);


--
-- Name: idx_gold_macro_event_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_gold_macro_event_date ON gold.macro_event_flags USING btree (date DESC);


--
-- Name: idx_gold_vix_regime_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_gold_vix_regime_date ON gold.vix_regime USING btree (date DESC);


--
-- Name: idx_ibkr_orders_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_ibkr_orders_strategy ON gold.ibkr_orders USING btree (strategy_id, ticker, status);


--
-- Name: idx_im_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_im_date ON gold.index_metrics USING btree (date DESC);


--
-- Name: idx_im_ticker_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_im_ticker_date ON gold.index_metrics USING btree (ticker, date DESC);


--
-- Name: idx_inst_holdings_ticker; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_inst_holdings_ticker ON gold.institutional_holdings USING btree (ticker);


--
-- Name: idx_kpis_ticker_date_desc; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_kpis_ticker_date_desc ON gold.kpis_metrics USING btree (ticker, date DESC);


--
-- Name: idx_paper_run_log_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_paper_run_log_date ON gold.paper_run_log USING btree (run_date);


--
-- Name: idx_paper_trades_status; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_paper_trades_status ON gold.paper_trades USING btree (status, rehearsal);


--
-- Name: idx_paper_trades_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_paper_trades_strategy ON gold.paper_trades USING btree (strategy_id, ts DESC) WHERE (rehearsal = false);


--
-- Name: idx_paper_trades_ts_closed; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_paper_trades_ts_closed ON gold.paper_trades USING btree (ts) WHERE (status = 'closed'::text);


--
-- Name: idx_regime_features_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_regime_features_date ON gold.regime_features USING btree (date);


--
-- Name: idx_s9_signals_active; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_s9_signals_active ON gold.s9_macd_signals USING btree (is_active);


--
-- Name: idx_s9_signals_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_s9_signals_date ON gold.s9_macd_signals USING btree (signal_date);


--
-- Name: idx_s9_signals_ticker; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_s9_signals_ticker ON gold.s9_macd_signals USING btree (ticker);


--
-- Name: idx_s9_trades_status; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_s9_trades_status ON gold.s9_paper_trades USING btree (status);


--
-- Name: idx_s9_trades_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_s9_trades_strategy ON gold.s9_paper_trades USING btree (strategy_id);


--
-- Name: idx_sbr_created; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sbr_created ON gold.strategy_backtest_runs USING btree (created_at DESC);


--
-- Name: idx_sbr_passed; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sbr_passed ON gold.strategy_backtest_runs USING btree (all_risk_gates_passed);


--
-- Name: idx_sbr_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sbr_strategy ON gold.strategy_backtest_runs USING btree (strategy_id);


--
-- Name: idx_sbt_period; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sbt_period ON gold.strategy_backtest_trades USING btree (period);


--
-- Name: idx_sbt_run; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sbt_run ON gold.strategy_backtest_trades USING btree (run_id);


--
-- Name: idx_sbt_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sbt_strategy ON gold.strategy_backtest_trades USING btree (strategy_id);


--
-- Name: idx_smh_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_smh_date ON gold.stock_metrics_history USING btree (date DESC);


--
-- Name: idx_smh_sector_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_smh_sector_date ON gold.stock_metrics_history USING btree (sector, date DESC);


--
-- Name: idx_smh_ticker_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_smh_ticker_date ON gold.stock_metrics_history USING btree (ticker, date DESC);


--
-- Name: idx_spl_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_spl_date ON gold.strategy_performance_log USING btree (log_date DESC);


--
-- Name: idx_spl_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_spl_strategy ON gold.strategy_performance_log USING btree (strategy_id);


--
-- Name: idx_sqr_decision; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sqr_decision ON gold.strategy_qa_reviews USING btree (decision);


--
-- Name: idx_sqr_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sqr_strategy ON gold.strategy_qa_reviews USING btree (strategy_id);


--
-- Name: idx_sr_asset; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sr_asset ON gold.strategy_research USING btree (asset_class);


--
-- Name: idx_sr_created; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sr_created ON gold.strategy_research USING btree (created_at DESC);


--
-- Name: idx_sr_parent; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sr_parent ON gold.strategy_research USING btree (parent_strategy_id);


--
-- Name: idx_sr_status; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sr_status ON gold.strategy_research USING btree (status);


--
-- Name: idx_sreg_asset; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sreg_asset ON gold.strategy_registry USING btree (asset_class);


--
-- Name: idx_sreg_status; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sreg_status ON gold.strategy_registry USING btree (status);


--
-- Name: idx_srr_decision; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_srr_decision ON gold.strategy_risk_reviews USING btree (decision);


--
-- Name: idx_srr_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_srr_strategy ON gold.strategy_risk_reviews USING btree (strategy_id);


--
-- Name: idx_ssc_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_ssc_strategy ON gold.strategy_signal_criteria USING btree (strategy_id);


--
-- Name: idx_stock_metrics_new_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_stock_metrics_new_date ON gold.stock_metrics_new USING btree (date);


--
-- Name: idx_stock_metrics_new_sector; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_stock_metrics_new_sector ON gold.stock_metrics_new USING btree (sector);


--
-- Name: idx_stock_metrics_new_ticker_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_stock_metrics_new_ticker_date ON gold.stock_metrics_new USING btree (ticker, date DESC);


--
-- Name: idx_strategy_definitions_execution_mode; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_strategy_definitions_execution_mode ON gold.strategy_definitions USING btree (execution_mode);


--
-- Name: idx_sts_action; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sts_action ON gold.strategy_ticker_scores USING btree (signal_action);


--
-- Name: idx_sts_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sts_strategy ON gold.strategy_ticker_scores USING btree (strategy_id);


--
-- Name: idx_su_strategy; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_su_strategy ON gold.strategy_universes USING btree (strategy_id, is_active);


--
-- Name: idx_sue_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sue_date ON gold.sue_scores USING btree (report_date DESC);


--
-- Name: idx_sue_decile; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sue_decile ON gold.sue_scores USING btree (sue_decile);


--
-- Name: idx_sue_ticker; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX idx_sue_ticker ON gold.sue_scores USING btree (ticker);


--
-- Name: ix_comm_metrics_ticker_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX ix_comm_metrics_ticker_date ON gold.commodity_metrics USING btree (ticker, date DESC);


--
-- Name: ix_crypto_metrics_ticker_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX ix_crypto_metrics_ticker_date ON gold.crypto_metrics USING btree (ticker, date DESC);


--
-- Name: ix_fx_metrics_ticker_date; Type: INDEX; Schema: gold; Owner: -
--

CREATE INDEX ix_fx_metrics_ticker_date ON gold.fx_metrics USING btree (ticker, date DESC);


--
-- Name: uq_paper_run_log_date_type; Type: INDEX; Schema: gold; Owner: -
--

CREATE UNIQUE INDEX uq_paper_run_log_date_type ON gold.paper_run_log USING btree (run_date, run_type) WHERE (status = ANY (ARRAY['ok'::text, 'halted'::text]));


--
-- Name: idx_daily_rca_date; Type: INDEX; Schema: research_sandbox; Owner: -
--

CREATE INDEX idx_daily_rca_date ON research_sandbox.daily_market_rca USING btree (date);


--
-- Name: idx_daily_rca_market; Type: INDEX; Schema: research_sandbox; Owner: -
--

CREATE INDEX idx_daily_rca_market ON research_sandbox.daily_market_rca USING btree (market);


--
-- Name: idx_strategy_ideas_date; Type: INDEX; Schema: research_sandbox; Owner: -
--

CREATE INDEX idx_strategy_ideas_date ON research_sandbox.daily_strategy_ideas USING btree (date);


--
-- Name: idx_market_indices_ticker_date; Type: INDEX; Schema: silver; Owner: -
--

CREATE INDEX idx_market_indices_ticker_date ON silver.market_indices USING btree (ticker, date DESC);


--
-- Name: idx_silver_asset_class; Type: INDEX; Schema: silver; Owner: -
--

CREATE INDEX idx_silver_asset_class ON silver.asset_registry USING btree (asset_class);


--
-- Name: idx_tech_ind_ticker_date; Type: INDEX; Schema: silver; Owner: -
--

CREATE INDEX idx_tech_ind_ticker_date ON silver.technical_indicators USING btree (ticker, date DESC);


--
-- Name: strategy_registry trg_strategy_registry_updated; Type: TRIGGER; Schema: gold; Owner: -
--

CREATE TRIGGER trg_strategy_registry_updated BEFORE UPDATE ON gold.strategy_registry FOR EACH ROW EXECUTE FUNCTION gold.set_updated_at();


--
-- Name: strategy_research trg_strategy_research_updated; Type: TRIGGER; Schema: gold; Owner: -
--

CREATE TRIGGER trg_strategy_research_updated BEFORE UPDATE ON gold.strategy_research FOR EACH ROW EXECUTE FUNCTION gold.set_updated_at();


--
-- Name: strategy_ticker_scores trg_strategy_ticker_scores_updated; Type: TRIGGER; Schema: gold; Owner: -
--

CREATE TRIGGER trg_strategy_ticker_scores_updated BEFORE UPDATE ON gold.strategy_ticker_scores FOR EACH ROW EXECUTE FUNCTION gold.set_updated_at();


--
-- Name: ibkr_historical_bars ibkr_historical_bars_con_id_fkey; Type: FK CONSTRAINT; Schema: bronze; Owner: -
--

ALTER TABLE ONLY bronze.ibkr_historical_bars
    ADD CONSTRAINT ibkr_historical_bars_con_id_fkey FOREIGN KEY (con_id) REFERENCES bronze.ibkr_contracts(con_id);


--
-- Name: s9_paper_trades s9_paper_trades_signal_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.s9_paper_trades
    ADD CONSTRAINT s9_paper_trades_signal_id_fkey FOREIGN KEY (signal_id) REFERENCES gold.s9_macd_signals(id);


--
-- Name: strategy_backtest_runs strategy_backtest_runs_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_backtest_runs
    ADD CONSTRAINT strategy_backtest_runs_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_research(strategy_id);


--
-- Name: strategy_backtest_trades strategy_backtest_trades_run_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_backtest_trades
    ADD CONSTRAINT strategy_backtest_trades_run_id_fkey FOREIGN KEY (run_id) REFERENCES gold.strategy_backtest_runs(run_id) ON DELETE CASCADE;


--
-- Name: strategy_configs strategy_configs_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_configs
    ADD CONSTRAINT strategy_configs_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_registry(strategy_id);


--
-- Name: strategy_performance_log strategy_performance_log_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_performance_log
    ADD CONSTRAINT strategy_performance_log_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_registry(strategy_id);


--
-- Name: strategy_qa_reviews strategy_qa_reviews_run_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_qa_reviews
    ADD CONSTRAINT strategy_qa_reviews_run_id_fkey FOREIGN KEY (run_id) REFERENCES gold.strategy_backtest_runs(run_id);


--
-- Name: strategy_qa_reviews strategy_qa_reviews_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_qa_reviews
    ADD CONSTRAINT strategy_qa_reviews_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_research(strategy_id);


--
-- Name: strategy_registry strategy_registry_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_registry
    ADD CONSTRAINT strategy_registry_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_research(strategy_id);


--
-- Name: strategy_research strategy_research_parent_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_research
    ADD CONSTRAINT strategy_research_parent_strategy_id_fkey FOREIGN KEY (parent_strategy_id) REFERENCES gold.strategy_research(strategy_id);


--
-- Name: strategy_risk_reviews strategy_risk_reviews_run_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_risk_reviews
    ADD CONSTRAINT strategy_risk_reviews_run_id_fkey FOREIGN KEY (run_id) REFERENCES gold.strategy_backtest_runs(run_id);


--
-- Name: strategy_risk_reviews strategy_risk_reviews_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_risk_reviews
    ADD CONSTRAINT strategy_risk_reviews_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_research(strategy_id);


--
-- Name: strategy_signal_criteria strategy_signal_criteria_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_signal_criteria
    ADD CONSTRAINT strategy_signal_criteria_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_registry(strategy_id);


--
-- Name: strategy_thresholds strategy_thresholds_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_thresholds
    ADD CONSTRAINT strategy_thresholds_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_registry(strategy_id);


--
-- Name: strategy_ticker_scores strategy_ticker_scores_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_ticker_scores
    ADD CONSTRAINT strategy_ticker_scores_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_registry(strategy_id);


--
-- Name: strategy_universes strategy_universes_strategy_id_fkey; Type: FK CONSTRAINT; Schema: gold; Owner: -
--

ALTER TABLE ONLY gold.strategy_universes
    ADD CONSTRAINT strategy_universes_strategy_id_fkey FOREIGN KEY (strategy_id) REFERENCES gold.strategy_registry(strategy_id);


--
-- PostgreSQL database dump complete
--

\unrestrict uxhuJhtme8CfCW3enj1ri3U0mG4rE0BF6efKrONXiWJsSJqvKuMyAMdyfccVOv0

