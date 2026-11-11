-- 2026-11-02 (kanban t_4df7ec1d): SUE freshness at month-end signal time.
--
-- Marks us_stk_sue_mom_01_v2 as a gold.sue_scores consumer. Two mechanisms
-- read this row:
--   1. ingest_paper_signal.py hard gate: a signal file for a marked strategy
--      MUST declare sue_scores_max_calculated_at and that vintage must be
--      fresh (<=2 calendar days) at the pinned signal date, else the ingest
--      fails closed (writes nothing for the strategy, exits non-zero).
--   2. gold/equity/refresh_sue_chain_monthend.py scopes its bronze earnings
--      scrape to the union of marked strategies' pinned universes.
--
-- Idempotent upsert; no strategy parameters touched.

INSERT INTO gold.strategy_configs (strategy_id, config_key, config_value, description, updated_at)
VALUES (
  'us_stk_sue_mom_01_v2',
  'requires_sue_scores',
  'true'::jsonb,
  't_4df7ec1d: signal engine sig_s1_v2 consumes gold.sue_scores; ingest gate '
  'fails closed when declared sue_scores_max_calculated_at is >2 calendar '
  'days older than the pinned signal date and fresher in-window scores exist.',
  NOW()
)
ON CONFLICT (strategy_id, config_key) DO UPDATE SET
  config_value = EXCLUDED.config_value,
  description  = EXCLUDED.description,
  updated_at   = NOW();
