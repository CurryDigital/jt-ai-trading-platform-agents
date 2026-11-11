-- 2026-11-03: Repoint gold.v_paper_trade_history (and v_paper_trade_summary) off the
-- orphaned legacy ledger gold.paper_trades (frozen 2026-08-05) onto the canonical
-- ledger gold.paper_trades_synthetic, PAPER-book scoped via gold.strategy_registry.
--
-- Root cause (kanban t_60df42bb): /api/agents/paper/trade-history returned 0 rows
-- because v_paper_trade_history read gold.paper_trades, which has received no new
-- rows since 2026-08-05 (t_274e2d7e repointed Command monthly_pnl.paper but not
-- these views). Canonical paper book = paper_trades_synthetic x registry
-- execution_mode='PAPER', CASH rows and CLEANSE-1 non-strategy closure legs
-- excluded (same predicate as backend app/services/bookkeeping.py
-- NON_STRATEGY_LEG_EXISTS). Verified 2026-11-03: 113 all-time / 40 last-30d closed
-- under this scope (matches Command overview all-time count of 113).
--
-- Window changed from opened-within-30d (legacy ts) to closed-within-30d
-- (exit_date): this is a closed-trade history surface.
-- Columns with no synthetic-ledger equivalent (instrument, contracts, regime,
-- ic_at_entry) are returned as NULL; the API endpoint tolerates nulls.

BEGIN;

-- No dependent views (verified 2026-11-03 via pg_depend); DROP required because
-- shares/hold_days/pnl_pct change type (integer -> numeric) vs the legacy def.
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
