-- Pure-SQL dedupe recompute for silver.historical_news (task t_f7f1c624)
-- Use for periodic full-table dedupe refresh (e.g. weekly) or after incremental
-- enrichment runs, whose within-batch dup detection misses cross-batch groups.
-- Mirrors the Python dedupe_key(): lower + keep [a-z0-9] tokens + date.

BEGIN;

WITH norm AS (
  SELECT id,
         date::date AS d,
         btrim(regexp_replace(lower(headline), '[^a-z0-9]+', ' ', 'g')) AS nh
  FROM silver.historical_news
),
grp AS (
  SELECT id,
         ('x' || substr(md5(d::text || '|' || nh), 1, 16))::bit(64)::bigint AS gid,
         COUNT(*) OVER (PARTITION BY d, nh) AS cnt
  FROM norm
)
UPDATE silver.historical_news h
SET dup_group_id = CASE WHEN g.cnt > 1 THEN g.gid ELSE NULL END,
    dup_count    = g.cnt
FROM grp g
WHERE h.id = g.id
  AND (h.dup_count IS DISTINCT FROM g.cnt
       OR h.dup_group_id IS DISTINCT FROM CASE WHEN g.cnt > 1 THEN g.gid ELSE NULL END);

COMMIT;

-- Note: the md5-based gid differs from the Python runner's group_id only in
-- normalization edge cases (Python keeps apostrophes inside words). Group
-- MEMBERSHIP is equivalent; do not mix gids produced by both in one analysis.
-- Prefer one producer; this SQL refresh is the recommended canonical one.
