-- 2026-10-09 (kanban t_835ba3c4): quarantine gold.strategy_backtests id 3 as
-- RETRACTED; mark ids 1-2 UNVERIFIED_NON_PIT; surface evidence_class on the
-- consumption feed (consumption.strategies_backtest_results) so the
-- Performance tab can badge UNVERIFIED rows and exclude them from rankings.
--
-- Background (user-directed legacy audit, qr_research 2026-10-09):
--   * id 3 (RSI(2) mean reversion) is byte-identical to id 2 (copy artifact),
--     has no writer script in tree, no provenance, and the strategy is not
--     enabled. RETRACTED = quarantined, NOT deleted (audit trail retained).
--   * ids 1-2: regime gate (if applied at all — writer script not in tree)
--     used gold.regime_label, which is rewritten nightly; the historical label
--     series is unrecoverable, so the metrics are not point-in-time and are
--     not comparable to PIT-audited OOS metrics.
--
-- evidence_class vocabulary (convention mirrors silver.option_eod_quotes.evidence_class):
--   QUOTED_CHAIN        (silver options) — as-quoted chain evidence
--   UNVERIFIED_NON_PIT  — metrics exist but are not point-in-time reproducible
--   RETRACTED           — quarantined artifact; must be excluded from all feeds
--
-- PERMANENT FLAG (Performance tab data sources):
--   Legacy signal-agent signals (gold.strategy_signals,
--   gold.regime_gate_decision_log) are sized with HARDCODED price=100.0,
--   atr14=2.0 (agents/signals/strategies/base_strategy.py BaseStrategy.run()
--   stub). position_size is NOT real. NO P&L may ever be derived from
--   gold.strategy_signals / gold.regime_gate_decision_log rows. Any future
--   shadow-PnL feature for these strategies must be rejected at review.

BEGIN;

-- ── gold layer: additive columns ─────────────────────────────────────────────
ALTER TABLE gold.strategy_backtests
    ADD COLUMN IF NOT EXISTS evidence_class text,
    ADD COLUMN IF NOT EXISTS verification_note text;

COMMENT ON COLUMN gold.strategy_backtests.evidence_class IS
    'Evidence class of the backtest row (convention mirrors silver.option_eod_quotes). '
    'NULL/UNVERIFIED_NON_PIT/RETRACTED. RETRACTED rows are quarantined and must be '
    'excluded from every consumption feed and ranking; UNVERIFIED_NON_PIT rows may be '
    'displayed only with an UNVERIFIED badge and must be excluded from rankings.';
COMMENT ON COLUMN gold.strategy_backtests.verification_note IS
    'Free-text audit note explaining the evidence_class assignment.';

-- id 3: RETRACTED (quarantine; do NOT delete — audit trail)
UPDATE gold.strategy_backtests
SET evidence_class   = 'RETRACTED',
    verification_note = 'Byte-identical copy artifact of strategy_id 2 (RSI(2) mean '
        'reversion); no writer script in tree, no provenance, strategy not enabled. '
        'Retracted 2026-10-09 (t_835ba3c4); row retained for audit trail only.'
WHERE strategy_id = 3 AND evidence_class IS NULL;

-- ids 1-2: UNVERIFIED_NON_PIT
UPDATE gold.strategy_backtests
SET evidence_class   = 'UNVERIFIED_NON_PIT',
    verification_note = 'regime gate (if applied at all — writer script not in tree) '
        'used gold.regime_label, nightly-rewritten; label series unrecoverable; '
        'not comparable to PIT-audited OOS metrics'
WHERE strategy_id IN (1, 2) AND evidence_class IS NULL;

COMMENT ON TABLE gold.strategy_backtests IS
    'Legacy smallint signal-agent backtest metrics (all rows run 2026-06-10). '
    'evidence_class governs consumption: RETRACTED = quarantined (never feed), '
    'UNVERIFIED_NON_PIT = display with UNVERIFIED badge, excluded from rankings. '
    'FLAG: legacy signal-agent position_size uses hardcoded price=100.0/atr14=2.0 '
    '(BaseStrategy.run stub) — no P&L may ever be derived from gold.strategy_signals '
    'or gold.regime_gate_decision_log.';

-- ── consumption layer: badge columns + purge/dedupe of the smallint rows ────
-- consumption.strategies_backtest_results is a DERIVED cache of
-- gold.strategy_backtests (fed by performance_strategy_results.py and
-- lab_strategy_scores.py). Both feeders historically used ON CONFLICT (id),
-- which never fires (id is serial) — every run appended fresh copies, leaving
-- 202 duplicate rows each for strategy_id '1','2','3'. Clean that up here:
--   * delete all rows for RETRACTED id '3' (must not appear on Performance tab)
--   * dedupe '1','2' to the latest copy each and badge them UNVERIFIED
-- The feeder scripts now DELETE-then-INSERT the gold-sourced strategy_ids and
-- exclude RETRACTED rows, so this state is maintained on every refresh.
ALTER TABLE consumption.strategies_backtest_results
    ADD COLUMN IF NOT EXISTS evidence_class text,
    ADD COLUMN IF NOT EXISTS verification_note text;

COMMENT ON COLUMN consumption.strategies_backtest_results.evidence_class IS
    'Carried from gold.strategy_backtests.evidence_class. UI contract: NULL = normal; '
    'UNVERIFIED_NON_PIT = show UNVERIFIED badge, exclude from ranking/leaderboard; '
    'RETRACTED rows are never present (excluded at feed time).';

DELETE FROM consumption.strategies_backtest_results
WHERE strategy_id = '3';

DELETE FROM consumption.strategies_backtest_results a
USING consumption.strategies_backtest_results b
WHERE a.strategy_id IN ('1','2')
  AND b.strategy_id = a.strategy_id
  AND b.id > a.id;

UPDATE consumption.strategies_backtest_results c
SET evidence_class    = g.evidence_class,
    verification_note = g.verification_note
FROM gold.strategy_backtests g
WHERE c.strategy_id = g.strategy_id::text
  AND g.strategy_id IN (1, 2);

COMMIT;
