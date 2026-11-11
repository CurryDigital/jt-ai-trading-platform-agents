-- 2026-11-02_entry_fill_convention.sql  (kanban t_716fe5a7)
--
-- Declare a SINGLE paper-ledger entry convention per book.
--
-- Background: gold.paper_trades_synthetic.entry_price_basis was MIXED within
-- the same books (Aug-vintage SIGNAL_CLOSE onboarding legs coexisting with
-- Sep/Oct NEXT_OPEN deferred-fill legs, plus NULL-basis rows from legacy
-- writers). Per IMPROVE-1 exact-logic pack flag (i), this blocked
-- exact-replica reconciliation and made P&L attribution convention-dependent.
--
-- Declaration: NEXT_OPEN for the nine reinstated books (CLEANSE-1 final
-- 2026-10-28). Same-close fills are explicitly NOT the production paper
-- convention (no-lookahead standard). The column is the authoritative
-- per-book declaration; rebuild_paper_positions.py resolves it (registry
-- declaration > strategy_configs fill_convention override > NEXT_OPEN
-- default) and fails closed on a declared value it cannot execute.
--
-- Historical mixed-basis rows are LEFT AS-IS with entry_price_basis as the
-- record (OPERATOR DECISION 2026-11-02: prospective-only; no restatement
-- without explicit sign-off). A label-only backfill for NULL-basis rows
-- (gold/strategy/label_null_entry_basis_2026-11-02.py) is prepared
-- dry-run-first and requires --apply + operator sign-off.

ALTER TABLE gold.strategy_registry
  ADD COLUMN IF NOT EXISTS entry_fill_convention TEXT;

ALTER TABLE gold.strategy_registry
  DROP CONSTRAINT IF EXISTS chk_entry_fill_convention;

-- No-lookahead policy at the data layer: same-close (SIGNAL_CLOSE) is not a
-- declarable production paper convention. T1_CLOSE is reserved for a future
-- engine mode (fill at the close of the first bar after the signal bar).
ALTER TABLE gold.strategy_registry
  ADD CONSTRAINT chk_entry_fill_convention
  CHECK (entry_fill_convention IS NULL
         OR entry_fill_convention IN ('NEXT_OPEN', 'T1_CLOSE'));

COMMENT ON COLUMN gold.strategy_registry.entry_fill_convention IS
  'Declared production paper-ledger entry fill convention (t_716fe5a7). '
  'NEXT_OPEN = fill at the open of the first bar after the signal bar '
  '(deferred orders, t_3454cc76). T1_CLOSE reserved, not yet engine-'
  'implemented. SIGNAL_CLOSE deliberately excluded (no-lookahead standard). '
  'Authoritative for rebuild_paper_positions.py resolution when set.';

-- Declare NEXT_OPEN for the nine reinstated books.
UPDATE gold.strategy_registry
SET entry_fill_convention = 'NEXT_OPEN',
    signal_logic = signal_logic || E'\n[Production paper entry convention: NEXT_OPEN — declared 2026-11-02 (t_716fe5a7). '
                   'Research-sim entry-at-signal-close text above describes the research variant only; '
                   'the entry_fill_convention column is authoritative for the paper ledger.]',
    updated_at = NOW()
WHERE strategy_id IN (
  'us_stk_sue_mom_01_v2',
  'ETF_Multi_Asset_Tactical_Allocation',
  'us_stk_lowbeta_14',
  'cn_stk_lowvol_12',
  'etf_vix_scaled_11',
  'ETF_US_Sector_Relative_Momentum',
  'etf_def_sector_rot_12_w',
  'COMM_Gold_Trend_VolTarget',
  'COMM_Copper_Trend_VolTarget'
);
