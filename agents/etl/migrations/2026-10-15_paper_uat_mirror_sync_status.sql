-- 2026-10-15_paper_uat_mirror_sync_status.sql
-- Heartbeat hardening (user directive 2026-10-16): a flat account and a
-- disconnected gateway must not look the same. The sync writes status='ok'
-- only after a successful positions fetch; a failed attempt writes
-- status='failed' + gateway_connected=false so the registry guard ERRORs
-- immediately instead of judging a stale snapshot for up to 3h.

ALTER TABLE gold.paper_uat_mirror_sync
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ok',
    ADD COLUMN IF NOT EXISTS gateway_connected boolean,
    ADD COLUMN IF NOT EXISTS error text;
