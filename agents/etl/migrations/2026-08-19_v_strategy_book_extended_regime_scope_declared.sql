-- kanban t_469a21c1: expose declared-vs-default regime_scope; backfill 3 missing registry rows
CREATE OR REPLACE VIEW gold.v_strategy_book_extended AS
 WITH latest_backtest AS (
         SELECT DISTINCT ON (strategy_backtest_runs.strategy_id) strategy_backtest_runs.strategy_id,
            strategy_backtest_runs.sharpe_oos AS sharpe_ratio,
            strategy_backtest_runs.returns_oos AS returns,
            strategy_backtest_runs.win_rate_oos AS win_rate,
            strategy_backtest_runs.max_drawdown_oos AS max_drawdown,
            strategy_backtest_runs.trade_count_oos AS trade_count,
            strategy_backtest_runs.turnover_oos AS turnover,
            strategy_backtest_runs.profit_factor_oos AS profit_factor,
            strategy_backtest_runs.cvar_95_oos AS cvar_95,
            strategy_backtest_runs.created_at AS backtest_date
           FROM gold.strategy_backtest_runs
          ORDER BY strategy_backtest_runs.strategy_id, strategy_backtest_runs.created_at DESC
        ), latest_trade AS (
         SELECT DISTINCT ON (paper_trades_synthetic.strategy_id) paper_trades_synthetic.strategy_id,
            paper_trades_synthetic.direction,
            paper_trades_synthetic.entry_price,
            (paper_trades_synthetic.created_at AT TIME ZONE 'UTC'::text) AS last_traded_at
           FROM gold.paper_trades_synthetic
          ORDER BY paper_trades_synthetic.strategy_id, paper_trades_synthetic.created_at DESC
        ), annual_pnl AS (
         SELECT DISTINCT ON (strategy_backtest_runs.strategy_id) strategy_backtest_runs.strategy_id,
            strategy_backtest_runs.annual_pnl_2024,
            strategy_backtest_runs.annual_pnl_2025,
            strategy_backtest_runs.annual_pnl_2026
           FROM gold.strategy_backtest_runs
          WHERE strategy_backtest_runs.annual_pnl_2024 IS NOT NULL OR strategy_backtest_runs.annual_pnl_2025 IS NOT NULL OR strategy_backtest_runs.annual_pnl_2026 IS NOT NULL
          ORDER BY strategy_backtest_runs.strategy_id, strategy_backtest_runs.created_at DESC
        ), live_stats AS (
         SELECT pt.strategy_id,
            sum(COALESCE(pt.pnl, 0::numeric)) AS live_pnl,
            count(*) AS live_trades,
                CASE
                    WHEN count(*) = 0 THEN NULL::numeric
                    ELSE sum(
                    CASE
                        WHEN COALESCE(pt.pnl, 0::numeric) > 0::numeric THEN 1
                        ELSE 0
                    END)::numeric / count(*)::numeric
                END AS live_win_rate
           FROM gold.paper_trades_synthetic pt
          WHERE pt.status = 'closed'::text
          GROUP BY pt.strategy_id
        )
 SELECT s.strategy_id,
    s.name,
    s.status,
    s.asset_class,
    s.entry_logic,
    s.exit_logic,
    s.source,
    b.sharpe_ratio,
    b.returns,
    b.win_rate,
    b.max_drawdown,
    b.trade_count,
    b.turnover,
    b.profit_factor,
    b.cvar_95,
    b.backtest_date,
    t.direction AS last_direction,
    t.entry_price AS last_entry_price,
    t.last_traded_at,
    pnl.annual_pnl_2024,
    pnl.annual_pnl_2025,
    pnl.annual_pnl_2026,
    ls.live_pnl,
    ls.live_win_rate,
    ls.live_trades,
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
            WHEN 'gold_seasonal'::text THEN 818624
            ELSE NULL::integer
        END AS min_nav_usd,
        CASE
            WHEN s.strategy_id::text = ANY (ARRAY['cl_cot_trend','cot_contrarian_extreme','gc_cot_contrarian_inverse','vix_spike_fade_entry','rsi_oversold_long','pead_long','btc_momentum_long','crude_seasonal','natgas_seasonal','gold_seasonal']::text[]) THEN true
            ELSE false
        END AS regime_scope_declared
   FROM gold.strategy_research s
     LEFT JOIN latest_backtest b ON b.strategy_id::text = s.strategy_id::text
     LEFT JOIN latest_trade t ON t.strategy_id = s.strategy_id::text
     LEFT JOIN annual_pnl pnl ON pnl.strategy_id::text = s.strategy_id::text
     LEFT JOIN live_stats ls ON ls.strategy_id = s.strategy_id::text
  ORDER BY (
        CASE s.status
            WHEN 'approved'::text THEN 1
            WHEN 'backtesting'::text THEN 2
            WHEN 'rejected'::text THEN 3
            ELSE 4
        END), s.strategy_id;;

-- Backfill 3 hand-mapped strategy_ids missing from gold.strategy_registry.
-- Statuses mirror research lifecycle: rejected -> retired, backtesting -> paused.
-- assigned_capital=0 so no consumer can interpret these as deployed.
INSERT INTO gold.strategy_registry
  (strategy_id, name, asset_class, universe_tickers, frequency, execution_mode,
   status, assigned_capital, in_market_capital, retired_at, retirement_reason, description)
VALUES ('vix_spike_fade_entry', 'VIX Spike Fade Entry (MES)', 'FX', ARRAY['MES']::varchar[], 'daily', 'SIMULATION',
        'retired', 0, 0, now(), 'invalid_synthetic_backtest_metrics: no trade log, cannot backfill profit factor', 'Registry backfill (kanban t_469a21c1): hand-mapped in gold.v_strategy_book_extended CASE but had no registry row; research status=rejected. Non-deploying (assigned_capital=0).')
ON CONFLICT (strategy_id) DO NOTHING;

INSERT INTO gold.strategy_registry
  (strategy_id, name, asset_class, universe_tickers, frequency, execution_mode,
   status, assigned_capital, in_market_capital, retired_at, retirement_reason, description)
VALUES ('btc_momentum_long', 'BTC Momentum Long', 'CRYPTO', ARRAY['BTC-USD']::varchar[], 'daily', 'SIMULATION',
        'retired', 0, 0, now(), 'invalid_synthetic_backtest_metrics: no trade log, cannot backfill profit factor', 'Registry backfill (kanban t_469a21c1): hand-mapped in gold.v_strategy_book_extended CASE but had no registry row; research status=rejected. Non-deploying (assigned_capital=0).')
ON CONFLICT (strategy_id) DO NOTHING;

INSERT INTO gold.strategy_registry
  (strategy_id, name, asset_class, universe_tickers, frequency, execution_mode,
   status, assigned_capital, in_market_capital, retired_at, retirement_reason, description)
VALUES ('rsi_oversold_long', 'RSI Mean Reversion — Oversold Long', 'equity', ARRAY['SPY']::varchar[], 'daily', 'SIMULATION',
        'paused', 0, 0, NULL, NULL, 'Registry backfill (kanban t_469a21c1): hand-mapped in gold.v_strategy_book_extended CASE but had no registry row; research status=backtesting. Non-deploying (assigned_capital=0).')
ON CONFLICT (strategy_id) DO NOTHING;

