BEGIN;

-- Rename the legacy static table so it remains available as reference/configuration.
ALTER TABLE IF EXISTS consumption.settings_data_sources
  SET SCHEMA gold;

ALTER TABLE IF EXISTS gold.settings_data_sources
  RENAME TO settings_data_sources_static;

COMMENT ON TABLE gold.settings_data_sources_static IS
  'Legacy static configuration for data sources (priority, fallback, is_active). '
  'Superseded by the consumption.settings_data_sources view which derives freshness from gold.source_freshness.';

-- Real-time consumption view over gold.source_freshness.
CREATE OR REPLACE VIEW consumption.settings_data_sources AS
WITH static_mapped AS (
    SELECT
        s.id,
        CASE s.data_type
            WHEN 'prices' THEN 'Market Data'
            WHEN 'earnings' THEN 'Fundamentals'
            WHEN 'fx' THEN 'FX'
            WHEN 'crypto' THEN 'Crypto'
            ELSE INITCAP(s.data_type)
        END AS category,
        s.data_type AS data_type,
        s.source_name AS primary_source,
        COALESCE(f.expected_frequency, 'daily') AS frequency,
        f.last_refreshed_at AS last_refreshed,
        CASE
            WHEN f.last_refreshed_at IS NULL THEN 'stale'
            WHEN f.last_refreshed_at < NOW() - ((f.expected_max_staleness_hours || ' hours')::INTERVAL) THEN 'stale'
            ELSE 'ok'
        END AS status
    FROM gold.settings_data_sources_static s
    LEFT JOIN gold.source_freshness f
      ON f.source = s.source_name
), freshness_only AS (
    SELECT
        NULL::int AS id,
        f.asset_class AS category,
        f.source AS data_type,
        f.source AS primary_source,
        f.expected_frequency AS frequency,
        f.last_refreshed_at AS last_refreshed,
        CASE
            WHEN f.last_refreshed_at IS NULL THEN 'stale'
            WHEN f.last_refreshed_at < NOW() - ((f.expected_max_staleness_hours || ' hours')::INTERVAL) THEN 'stale'
            ELSE 'ok'
        END AS status
    FROM gold.source_freshness f
    WHERE f.source NOT IN (SELECT source_name FROM gold.settings_data_sources_static)
)
SELECT * FROM static_mapped
UNION ALL
SELECT * FROM freshness_only
ORDER BY category, primary_source;

COMMENT ON VIEW consumption.settings_data_sources IS
  'Real-time data source freshness for the Settings Data Sources tab. '
  'Sources configured in the legacy static table keep their category mapping; '
  'all other sources in gold.source_freshness are exposed as-is.';

COMMIT;
