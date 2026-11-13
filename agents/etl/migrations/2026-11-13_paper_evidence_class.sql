-- 2026-11-13: separate historical replay from forward Paper evidence.
--
-- Root cause: gold.paper_trades_synthetic was both the forward Paper ledger
-- (rebuild_paper_positions.py) and the historical replay ledger
-- (refresh_paper_trades_synthetic.py). Paper surfaces could therefore present
-- reconstructed signal history as if it were forward Paper evidence.
--
-- Contract after this migration:
--   * forward_paper       = rows booked by the forward position-aware engine
--   * historical_replay   = rows reconstructed from signal history
--   * legacy_unclassified = pre-migration rows without sufficient provenance
--
-- Only forward_paper rows may feed Paper positions/metrics. Historical replay
-- remains stored for research/shadow-ledger audit, but is not Paper evidence.
-- Legacy rows stay visible in the raw ledger, never in Paper surfaces. Do not
-- heuristic-backfill legacy_unclassified rows without row-level provenance.

BEGIN;

ALTER TABLE gold.paper_trades_synthetic
  ADD COLUMN IF NOT EXISTS evidence_class TEXT;

UPDATE gold.paper_trades_synthetic
SET evidence_class = 'legacy_unclassified'
WHERE evidence_class IS NULL;

ALTER TABLE gold.paper_trades_synthetic
  ALTER COLUMN evidence_class SET DEFAULT 'legacy_unclassified',
  ALTER COLUMN evidence_class SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE n.nspname = 'gold'
      AND t.relname = 'paper_trades_synthetic'
      AND c.conname = 'paper_trades_synthetic_evidence_class_chk'
  ) THEN
    ALTER TABLE gold.paper_trades_synthetic
      ADD CONSTRAINT paper_trades_synthetic_evidence_class_chk
      CHECK (evidence_class IN (
        'forward_paper', 'historical_replay', 'legacy_unclassified'
      ));
  END IF;
END $$;

-- Rows with append-only feeder provenance are replay even when they were
-- refreshed after Paper monitoring began. This is the only automatic
-- historical classification trusted by this migration.
UPDATE gold.paper_trades_synthetic pts
SET evidence_class = 'historical_replay'
WHERE EXISTS (
  SELECT 1
  FROM gold.paper_feeder_runs r
  WHERE r.feeder = 'refresh_paper_trades_synthetic'
    AND (r.run_id = pts.run_id OR r.run_id = pts.exit_run_id)
);

-- The replay feeder and one-off simulation ingests did not stamp a fill basis.
-- Unbased rows are historical replay, not forward Paper fills.
UPDATE gold.paper_trades_synthetic
SET evidence_class = 'historical_replay'
WHERE evidence_class = 'legacy_unclassified'
  AND entry_price_basis IS NULL;

-- NEXT_OPEN basis was introduced by the forward position-aware engine.
-- SIGNAL_CLOSE remains unclassified here because both the forward engine and
-- historical repair scripts can write that basis; classifying it requires
-- row-level provenance rather than a heuristic.
UPDATE gold.paper_trades_synthetic
SET evidence_class = 'forward_paper'
WHERE evidence_class = 'legacy_unclassified'
  AND entry_price_basis IN ('NEXT_OPEN', 'NEXT_OPEN_CLOSE_FALLBACK');

CREATE INDEX IF NOT EXISTS idx_pts_forward_evidence
  ON gold.paper_trades_synthetic (strategy_id, status)
  WHERE evidence_class = 'forward_paper';

COMMENT ON COLUMN gold.paper_trades_synthetic.evidence_class IS
  'Evidence class: forward_paper rows are booked by the forward engine; historical_replay rows are reconstructed from signal history; legacy_unclassified rows lack sufficient provenance and must not feed Paper surfaces.';

-- Pipeline feed: Paper metrics only from forward evidence.
CREATE OR REPLACE VIEW gold.v_pipeline_ui_feed AS
 WITH latest_backtest AS (
         SELECT DISTINCT ON (strategy_backtest_runs.strategy_id) strategy_backtest_runs.strategy_id,
            strategy_backtest_runs.run_id,
            strategy_backtest_runs.annual_pnl_2025,
            strategy_backtest_runs.annual_pnl_2026,
            strategy_backtest_runs.annual_pnl_2024,
            strategy_backtest_runs.sharpe_oos,
            strategy_backtest_runs.returns_oos,
            strategy_backtest_runs.max_drawdown_oos,
            strategy_backtest_runs.trade_count_oos,
            strategy_backtest_runs.win_rate_oos,
            strategy_backtest_runs.profit_factor_oos,
            strategy_backtest_runs.all_risk_gates_passed
           FROM (gold.strategy_backtest_runs
             LEFT JOIN gold.strategy_registry reg_match ON (((reg_match.strategy_id)::text = (strategy_backtest_runs.strategy_id)::text)))
          ORDER BY strategy_backtest_runs.strategy_id, strategy_backtest_runs.created_at DESC, ((NOT (strategy_backtest_runs.sharpe_oos IS DISTINCT FROM reg_match.sharpe_oos)) AND (NOT (abs(strategy_backtest_runs.max_drawdown_oos) IS DISTINCT FROM abs(reg_match.max_drawdown_oos))) AND (NOT (strategy_backtest_runs.trade_count_oos IS DISTINCT FROM reg_match.trade_count_oos))) DESC, strategy_backtest_runs.run_id
        ), latest_ticker_score AS (
         SELECT DISTINCT ON (strategy_ticker_scores.strategy_id) strategy_ticker_scores.strategy_id,
            strategy_ticker_scores.signal_action,
            strategy_ticker_scores.position_status,
            strategy_ticker_scores.score
           FROM gold.strategy_ticker_scores
          ORDER BY strategy_ticker_scores.strategy_id, strategy_ticker_scores.updated_at DESC
        ), strategy_capital AS (
         SELECT strategy_registry.strategy_id,
            strategy_registry.assigned_capital
           FROM gold.strategy_registry
        ), paper_monitoring AS (
         SELECT strategy_paper_monitoring.strategy_id,
            strategy_paper_monitoring.is_active
           FROM gold.strategy_paper_monitoring
        ), live_metrics AS (
         SELECT pts.strategy_id,
            COALESCE(((sum(pts.pnl) / NULLIF(sc.assigned_capital, (0)::numeric)) * (100)::numeric), NULL::numeric) AS live_pnl,
                CASE
                    WHEN (count(*) FILTER (WHERE (pts.status = 'closed'::text)) > 0) THEN (((count(*) FILTER (WHERE ((pts.status = 'closed'::text) AND (pts.pnl > (0)::numeric))))::numeric * 100.0) / (NULLIF(count(*) FILTER (WHERE (pts.status = 'closed'::text)), 0))::numeric)
                    ELSE NULL::numeric
                END AS livewr,
                CASE
                    WHEN (sum(pts.pnl) FILTER (WHERE ((pts.status = 'closed'::text) AND (pts.pnl < (0)::numeric))) < (0)::numeric) THEN (COALESCE(sum(pts.pnl) FILTER (WHERE ((pts.status = 'closed'::text) AND (pts.pnl > (0)::numeric))), (0)::numeric) / NULLIF(abs(sum(pts.pnl) FILTER (WHERE ((pts.status = 'closed'::text) AND (pts.pnl < (0)::numeric)))), (0)::numeric))
                    ELSE NULL::numeric
                END AS livepf,
            count(*) FILTER (WHERE (pts.status = 'closed'::text)) AS live_trades_closed
           FROM ((gold.paper_trades_synthetic pts
             JOIN strategy_capital sc ON (((sc.strategy_id)::text = pts.strategy_id)))
             JOIN paper_monitoring pm ON (((pm.strategy_id = pts.strategy_id) AND (pm.is_active = true))))
          WHERE pts.evidence_class = 'forward_paper'
          GROUP BY pts.strategy_id, sc.assigned_capital
        ), synthetic_metrics AS (
         SELECT live_metrics.strategy_id,
            live_metrics.live_pnl AS live_pnl_synthetic,
            live_metrics.livewr AS livewr_synthetic,
            live_metrics.livepf AS livepf_synthetic,
            live_metrics.live_trades_closed AS synthetic_trades_closed
           FROM live_metrics
        ), current_year_wr AS (
         SELECT sbt.strategy_id,
            count(*) FILTER (WHERE ((sbt.exit_date IS NOT NULL) AND (EXTRACT(year FROM sbt.exit_date) = EXTRACT(year FROM CURRENT_DATE)))) AS cy_closed,
            count(*) FILTER (WHERE ((sbt.exit_date IS NOT NULL) AND (EXTRACT(year FROM sbt.exit_date) = EXTRACT(year FROM CURRENT_DATE)) AND (sbt.pnl_pct > (0)::numeric))) AS cy_wins
           FROM (gold.strategy_backtest_trades sbt
             JOIN latest_backtest lb ON ((lb.run_id = sbt.run_id)))
          GROUP BY sbt.strategy_id
        ), published AS (
         SELECT r.strategy_id,
            r.name,
            r.asset_class,
            r.frequency,
            r.execution_mode,
            r.status AS registry_status,
            r.priority,
            r.approved_at,
            r.updated_at,
            res.status AS research_status,
            r.paper_tier,
            r.paper_tier_blocker,
            b.sharpe_oos,
            b.returns_oos,
            b.max_drawdown_oos,
            b.trade_count_oos,
            b.win_rate_oos,
            b.profit_factor_oos,
            b.all_risk_gates_passed,
            lts.position_status AS paper_position_status,
            lts.score,
            COALESCE(pm.is_active, false) AS is_paper_monitoring,
            (((r.priority)::text = ANY (ARRAY['EXPERIMENTAL'::text, 'NEAR_GOLDEN'::text, 'GOLDEN'::text])) AND ((r.status)::text <> ALL (ARRAY['retired'::text])) AND (((r.status)::text <> 'paused'::text) OR ((r.execution_mode)::text = 'SIMULATION'::text)) AND ((res.status)::text <> ALL (ARRAY['rejected'::text, 'retired'::text])) AND (b.sharpe_oos >= 0.5) AND (abs(COALESCE(b.max_drawdown_oos, (0)::numeric)) <= 0.20) AND ((b.trade_count_oos >= 30) OR ((r.strategy_id)::text = ANY (ARRAY['HK_Quality_BlueChips'::text, 'us_stk_sue_mom_01_v2'::text, 'hk_stk_52wh_mom_04'::text, 'etf_tsmom_basket_07'::text, 'etf_country_rot_10_v2'::text, 'cn_stk_lowvol_12'::text, 'sg_stk_52wh_mom_13'::text, 'us_stk_lowbeta_14'::text, 'etf_vix_scaled_11'::text, 'etf_tech_mom_13'::text, 'etf_def_sector_rot_12_w'::text, 'etf_comm_trend_basket_15'::text, 'crisis_safe_haven_vt_19'::text, 'hk_ipo_day1_green_momentum_v1'::text, 'hk_ipo_postlisting_drift_c1'::text, 'us_vix_spike_crisis_event_v3'::text]))) AND (b.returns_oos IS NOT NULL)) AS publishable,
            b.annual_pnl_2025,
            b.annual_pnl_2026,
            b.annual_pnl_2024
           FROM ((((gold.strategy_registry r
             JOIN gold.strategy_research res ON (((res.strategy_id)::text = (r.strategy_id)::text)))
             LEFT JOIN latest_backtest b ON (((b.strategy_id)::text = (r.strategy_id)::text)))
             LEFT JOIN latest_ticker_score lts ON (((lts.strategy_id)::text = (r.strategy_id)::text)))
             LEFT JOIN paper_monitoring pm ON ((pm.strategy_id = (r.strategy_id)::text)))
        )
 SELECT s.strategy_id AS id,
    s.name,
    COALESCE(upper((s.asset_class)::text), 'EQUITY'::text) AS asset,
        CASE
            WHEN ((s.frequency)::text = ANY (ARRAY['daily'::text, 'intraday'::text, 'day'::text, 'event'::text])) THEN 'day'::text
            WHEN ((s.frequency)::text = ANY (ARRAY['weekly'::text, 'swing'::text])) THEN 'swing'::text
            WHEN ((s.frequency)::text = ANY (ARRAY['monthly'::text, 'quarterly'::text, 'position'::text])) THEN 'position'::text
            ELSE 'swing'::text
        END AS horizon,
        CASE
            WHEN (upper((s.priority)::text) = 'GOLDEN'::text) THEN 'T1'::text
            WHEN (upper((s.priority)::text) = 'NEAR_GOLDEN'::text) THEN 'T2'::text
            ELSE 'T3'::text
        END AS tier,
        CASE
            WHEN ((upper((s.priority)::text) = 'GOLDEN'::text) AND (s.approved_at IS NOT NULL)) THEN 'golden'::text
            WHEN ((upper((s.priority)::text) = 'NEAR_GOLDEN'::text) AND (s.approved_at IS NOT NULL)) THEN 'near_golden'::text
            WHEN ((upper((s.priority)::text) = 'GOLDEN'::text) AND (s.approved_at IS NULL)) THEN 'near_golden'::text
            WHEN ((upper((s.priority)::text) = 'NEAR_GOLDEN'::text) AND (s.approved_at IS NULL)) THEN 'experimental'::text
            WHEN (((s.registry_status)::text = 'paper'::text) AND s.is_paper_monitoring) THEN 'golden'::text
            WHEN ((s.registry_status)::text = 'live'::text) THEN 'deployed'::text
            ELSE 'experimental'::text
        END AS stage,
    (s.win_rate_oos * (100)::numeric) AS btwr,
        CASE
            WHEN s.is_paper_monitoring THEN lm.livewr
            ELSE NULL::numeric
        END AS livewr,
    s.profit_factor_oos AS btpf,
        CASE
            WHEN s.is_paper_monitoring THEN lm.livepf
            ELSE NULL::numeric
        END AS livepf,
    s.trade_count_oos AS trades,
    (s.returns_oos * (100)::numeric) AS returns,
    (s.sharpe_oos)::numeric AS sharpe,
    ((- abs(COALESCE(s.max_drawdown_oos, (0)::numeric))) * (100)::numeric) AS dd,
        CASE
            WHEN s.is_paper_monitoring THEN 'PAPER_TRADING'::text
            WHEN ((s.registry_status)::text = 'live'::text) THEN 'LIVE_TRADING'::text
            ELSE 'SIMULATION'::text
        END AS mode,
    NULL::jsonb AS margin,
    s.research_status AS db_status,
    s.frequency,
    'trade_algo_researcher'::text AS agent_source,
    s.updated_at,
        CASE
            WHEN s.is_paper_monitoring THEN lm.live_pnl
            ELSE NULL::numeric
        END AS live_pnl,
    sm.livewr_synthetic,
    sm.livepf_synthetic,
    sm.live_pnl_synthetic,
        CASE
            WHEN (NOT s.publishable) THEN 'not_publishable'::text
            WHEN ((s.profit_factor_oos IS NULL) AND (s.trade_count_oos > 0)) THEN 'missing_pf'::text
            WHEN ((s.sharpe_oos IS NULL) AND (s.trade_count_oos > 0)) THEN 'missing_sharpe'::text
            WHEN ((abs(COALESCE(s.max_drawdown_oos, (0)::numeric)) = (0)::numeric) AND (s.trade_count_oos > 1)) THEN 'suspicious_zero_dd'::text
            ELSE 'ok'::text
        END AS metric_valid_flag,
    (s.annual_pnl_2025 * (100)::numeric) AS annual_pnl_2025,
    (s.annual_pnl_2026 * (100)::numeric) AS annual_pnl_2026,
    (s.annual_pnl_2024 * (100)::numeric) AS annual_pnl_2024,
    (((cw.cy_wins)::numeric * 100.0) / (NULLIF(cw.cy_closed, 0))::numeric) AS current_year_wr,
    s.is_paper_monitoring,
    s.paper_tier,
    s.paper_tier_blocker
   FROM (((published s
     LEFT JOIN live_metrics lm ON ((lm.strategy_id = (s.strategy_id)::text)))
     LEFT JOIN synthetic_metrics sm ON ((sm.strategy_id = (s.strategy_id)::text)))
     LEFT JOIN current_year_wr cw ON (((cw.strategy_id)::text = (s.strategy_id)::text)))
  WHERE s.publishable
  ORDER BY
        CASE
            WHEN ((upper((s.priority)::text) = 'GOLDEN'::text) AND (s.approved_at IS NOT NULL)) THEN 'golden'::text
            WHEN ((upper((s.priority)::text) = 'NEAR_GOLDEN'::text) AND (s.approved_at IS NOT NULL)) THEN 'near_golden'::text
            WHEN ((upper((s.priority)::text) = 'GOLDEN'::text) AND (s.approved_at IS NULL)) THEN 'near_golden'::text
            WHEN ((upper((s.priority)::text) = 'NEAR_GOLDEN'::text) AND (s.approved_at IS NULL)) THEN 'experimental'::text
            WHEN (((s.registry_status)::text = 'paper'::text) AND s.is_paper_monitoring) THEN 'golden'::text
            WHEN ((s.registry_status)::text = 'live'::text) THEN 'deployed'::text
            ELSE 'experimental'::text
        END, s.updated_at DESC;

-- Strategy book: latest-trade and live-stat surfaces only from forward evidence.
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
          WHERE paper_trades_synthetic.evidence_class = 'forward_paper'
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
            AND pt.evidence_class = 'forward_paper'
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
        END), s.strategy_id;

-- Closed-trade Paper history/summary: forward evidence only.
DROP VIEW IF EXISTS gold.v_paper_trade_summary;
DROP VIEW IF EXISTS gold.v_paper_trade_history;

CREATE VIEW gold.v_paper_trade_history AS
SELECT t.id,
       t.strategy_id,
       NULL::text        AS instrument,
       t.ticker,
       t.direction,
       NULL::numeric     AS contracts,
       t.n_shares        AS shares,
       t.entry_price,
       t.exit_price,
       t.pnl,
       t.pnl_pct,
       NULL::text        AS regime,
       NULL::numeric     AS ic_at_entry,
       t.entry_date      AS opened_at,
       t.exit_date       AS closed_at,
       (t.exit_date - t.entry_date) AS hold_days
FROM gold.paper_trades_synthetic t
JOIN gold.strategy_registry r ON r.strategy_id = t.strategy_id
WHERE t.status = 'closed'
  AND t.evidence_class = 'forward_paper'
  AND r.execution_mode = 'PAPER'
  AND t.exit_date >= now()::date - 30
  AND (t.ticker IS NULL OR t.ticker != 'CASH')
  AND NOT EXISTS (
      SELECT 1 FROM gold.paper_trade_skip_log k
      WHERE k.strategy_id = t.strategy_id
        AND k.ticker = t.ticker
        AND k.skip_date = t.exit_date
        AND (k.skip_kind = 'CLEANSE1_CLOSURE'
             OR (k.skip_kind = 'RESET_STALE_SIGNAL' AND k.reason ILIKE '%flattened%'))
  )
ORDER BY t.exit_date DESC, t.id DESC;

CREATE VIEW gold.v_paper_trade_summary AS
SELECT count(*) AS total_trades,
       round(sum(CASE WHEN t.pnl > 0::numeric THEN 1 ELSE 0 END)::numeric
             / NULLIF(count(*), 0)::numeric * 100::numeric, 1) AS win_rate_pct,
       round(sum(t.pnl), 2) AS total_pnl,
       round(avg(t.pnl), 2) AS avg_pnl,
       round(min(t.pnl), 2) AS max_loss,
       round(max(t.pnl), 2) AS max_win,
       (SELECT max(paper_run_log.drawdown_pct)
          FROM gold.paper_run_log
         WHERE paper_run_log.run_date >= (now() - '30 days'::interval)) AS max_drawdown_pct
FROM gold.paper_trades_synthetic t
JOIN gold.strategy_registry r ON r.strategy_id = t.strategy_id
WHERE t.status = 'closed'
  AND t.evidence_class = 'forward_paper'
  AND r.execution_mode = 'PAPER'
  AND t.exit_date >= now()::date - 30
  AND (t.ticker IS NULL OR t.ticker != 'CASH')
  AND NOT EXISTS (
      SELECT 1 FROM gold.paper_trade_skip_log k
      WHERE k.strategy_id = t.strategy_id
        AND k.ticker = t.ticker
        AND k.skip_date = t.exit_date
        AND (k.skip_kind = 'CLEANSE1_CLOSURE'
             OR (k.skip_kind = 'RESET_STALE_SIGNAL' AND k.reason ILIKE '%flattened%'))
  );

COMMIT;
