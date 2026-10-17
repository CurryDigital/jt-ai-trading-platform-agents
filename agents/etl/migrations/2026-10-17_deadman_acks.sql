-- gold.deadman_acks: acknowledged-alert registry (user directive 2026-10-17)
-- The deadman alerts once on a new condition; a known-and-accepted condition
-- is acked with reason + hard expiry and stays silent until expiry. Any
-- alert whose key is NOT acked still fires nightly. Expiry past due = the
-- alert fires again (self-un-acking).
CREATE TABLE IF NOT EXISTS gold.deadman_acks (
    alert_key   text PRIMARY KEY,   -- prefix-matched against the alert text
    reason      text NOT NULL,
    expires     date NOT NULL,      -- alert resumes the day AFTER this date
    created_by  text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- Seed: the 5 frozen ingested strategies (stale since 2026-08-05; see
-- workspace/strategy_audit/etf_tsmom_basket_07_2026-10-16.md and
-- stale_ingested_strategies_2026-10-17.md). Expiry = day before the
-- 2026-11-01 rebalance so a stale score set CANNOT silently pass November.
INSERT INTO gold.deadman_acks (alert_key, reason, expires, created_by) VALUES
 ('SIGNAL STALE: etf_tsmom_basket_07',
  'Research-side non-delivery since 2026-08-05 (ingested signals frozen); user-acknowledged 2026-10-17; research recompute due before Nov rebalance',
  DATE '2026-10-31', 'qr_etl'),
 ('SIGNAL STALE: us_stk_sue_mom_01_v2',
  'Research-side non-delivery since 2026-08-05 (ingested signals frozen); user-acknowledged 2026-10-17; research recompute due before Nov rebalance',
  DATE '2026-10-31', 'qr_etl'),
 ('SIGNAL STALE: hk_stk_52wh_mom_04',
  'Research-side non-delivery since 2026-08-05 (ingested signals frozen); user-acknowledged 2026-10-17; research recompute due before Nov rebalance',
  DATE '2026-10-31', 'qr_etl'),
 ('SIGNAL STALE: us_stk_lowbeta_14',
  'Research-side non-delivery since 2026-08-05 (ingested signals frozen); user-acknowledged 2026-10-17; research recompute due before Nov rebalance',
  DATE '2026-10-31', 'qr_etl'),
 ('SIGNAL STALE: cn_stk_lowvol_12',
  'Research-side non-delivery since 2026-08-05 (ingested signals frozen); user-acknowledged 2026-10-17; research recompute due before Nov rebalance',
  DATE '2026-10-31', 'qr_etl')
ON CONFLICT (alert_key) DO UPDATE SET
    reason = EXCLUDED.reason, expires = EXCLUDED.expires;
