-- 2026-10-28 (t_33ffe715): per-book paper deployment ratio surface.
--
-- consumption.strategy_paper_deployment_current holds ONE row per active
-- paper strategy, refreshed by rebuild_paper_positions.py on every run
-- (same refresh pattern as consumption.strategy_paper_skips_current).
--
-- Purpose: whole-lot + concentration-cap quantization drag parks capital in
-- cash, but the UI skip badge only shows PER-SIGNAL skips. A book can read
-- "clean" while 15% of its deployable budget never left cash. This table
-- surfaces the steady-state deployment ratio so the drag is visible per
-- strategy tile.
--
-- Definitions (writer: gold/strategy/rebuild_paper_positions.py):
--   target_notional       deployable budget = assigned_capital * BUY-score
--                         share (mirrors compute_target / deployable_budget;
--                         the CASH signal share is intentionally NOT part of
--                         the target — it is designed cash, not drag).
--   invested_notional     post-run open-position cost basis
--                         (sum n_shares * entry_price over open rows).
--   pending_open_notional resting NEXT_OPEN entry orders valued at the
--                         signal-bar close (committed but not yet filled).
--   committed_notional    invested + pending.
--   deployment_ratio      committed / target_notional (NULL when target = 0).
--                         < 1.0 = lot/cap quantization drag.
--   capital_utilization   committed / assigned_capital (NULL when capital = 0).
--                         Includes the designed CASH residual in the gap.
--   undeployed_notional   target_notional - committed_notional (raw; small
--                         negative values possible from clamp rounding).
--   skips_by_kind         jsonb {skip_kind: count} for the run (BELOW_ONE_LOT,
--                         CONCENTRATION_CAP, CADENCE_GATE, OVER_DEPLOYED, ...).
--   max_position_pct      concentration cap actually applied this run.
--
-- PAPER_UAT strategies get NO row: their DB ledger is empty by design
-- (broker session is book-of-record), so a computed ratio would falsely
-- read 0% deployed. The writer deletes stale rows for UAT books and for
-- strategies that leave the active rebuild set.

CREATE TABLE IF NOT EXISTS consumption.strategy_paper_deployment_current (
  strategy_id           TEXT PRIMARY KEY,
  run_date              DATE NOT NULL,
  assigned_capital      NUMERIC,
  target_notional       NUMERIC,
  invested_notional     NUMERIC,
  pending_open_notional NUMERIC,
  committed_notional    NUMERIC,
  deployment_ratio      NUMERIC(9,6),
  capital_utilization   NUMERIC(9,6),
  undeployed_notional   NUMERIC,
  skips_by_kind         JSONB,
  max_position_pct      NUMERIC,
  updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE consumption.strategy_paper_deployment_current IS
'Per-strategy paper-book deployment ratio (committed/target and '
'committed/assigned_capital), refreshed every rebuild_paper_positions.py '
'run. Surfaces whole-lot + concentration-cap quantization cash drag on the '
'strategy tile. t_33ffe715.';
