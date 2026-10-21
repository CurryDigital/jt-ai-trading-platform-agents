-- Kanban t_03fc7ddb: LLM news-signal accountability layer.
--
-- consumption.news_signal_events
--   Persistent ledger of every LLM cluster assessment captured from
--   consumption.news_outlook (qr_research writes one run_date batch per day,
--   upserted at 15:30/21:30 UTC). news_clusters itself is rebuilt wholesale
--   every 2h (48h window), so first_seen_utc / primary ticker must be frozen
--   here at capture time or the history is lost.
--   Forward returns (ret_1d / ret_5d from gold.daily_ohlcv, session-based;
--   ret_1h from bronze.ibkr_historical_bars) are filled in as data matures.
--
-- consumption.news_signal_performance
--   Rolling 30d/90d aggregate hit-rate / mean-return / information
--   coefficient, segmented overall / asset_class / confidence_bucket, plus
--   coverage rows (segment_type='coverage': pct of clusters with a resolvable
--   primary ticker). Serves GET /api/news/signal-performance.

CREATE TABLE IF NOT EXISTS consumption.news_signal_events (
    run_date          DATE         NOT NULL,
    cluster_key       VARCHAR(32)  NOT NULL,
    category          VARCHAR(8)   NOT NULL,           -- US/HK/CRYPTO/FX/METAL
    headline          TEXT,
    bias              VARCHAR(10)  NOT NULL,           -- bullish/bearish/neutral/mixed
    confidence        NUMERIC(4,3),
    horizon           VARCHAR(10),
    -- ticker + anchor resolution (frozen at capture time)
    primary_ticker    VARCHAR(16),                     -- NULL = unresolvable
    ticker_source     VARCHAR(20)  NOT NULL DEFAULT 'none',
        -- 'cluster_tickers' | 'affected_assets' | 'none'
    cluster_id        VARCHAR(32),                     -- matched news_clusters row, if any
    cluster_match     VARCHAR(20)  NOT NULL DEFAULT 'none',
        -- 'exact_key' | 'headline_jaccard' | 'none'
    first_seen_utc    TIMESTAMP,                       -- anchor; fallback source_latest
    anchor_source     VARCHAR(24)  NOT NULL DEFAULT 'run_date',
        -- 'cluster_first_seen' | 'source_latest' | 'run_date'
    captured_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    -- forward returns of primary_ticker after first_seen anchor
    ret_1h            NUMERIC(10,5),
    ret_1h_status     VARCHAR(24)  NOT NULL DEFAULT 'pending',
        -- 'ok' | 'unavailable_stale_source' | 'no_ticker' | 'pending'
    ret_1d            NUMERIC(10,5),
    ret_1d_status     VARCHAR(24)  NOT NULL DEFAULT 'pending',
        -- 'ok' | 'no_ticker' | 'no_price_data' | 'pending' (awaiting sessions)
    ret_5d            NUMERIC(10,5),
    ret_5d_status     VARCHAR(24)  NOT NULL DEFAULT 'pending',
    base_close        NUMERIC(18,6),
    base_close_date   DATE,
    returns_computed_at TIMESTAMP,
    PRIMARY KEY (run_date, cluster_key)
);

CREATE INDEX IF NOT EXISTS idx_news_signal_events_anchor
    ON consumption.news_signal_events (first_seen_utc);
CREATE INDEX IF NOT EXISTS idx_news_signal_events_ticker
    ON consumption.news_signal_events (primary_ticker);

CREATE TABLE IF NOT EXISTS consumption.news_signal_performance (
    horizon           VARCHAR(4)   NOT NULL,           -- '1h','1d','5d'
    "window"          VARCHAR(4)   NOT NULL,           -- '30d','90d' (quoted: reserved)
    segment_type      VARCHAR(20)  NOT NULL,
        -- 'overall' | 'asset_class' | 'confidence_bucket' | 'coverage'
    segment_value     VARCHAR(32)  NOT NULL,           -- 'all', asset class, '0-20',..
    hit_rate          NUMERIC(6,4),                    -- NULL for coverage rows
    mean_return       NUMERIC(10,5),
    information_coefficient NUMERIC(6,4),              -- Spearman dir*conf vs ret
    coverage_pct      NUMERIC(6,4),                    -- only coverage rows
    sample_size       INTEGER      NOT NULL DEFAULT 0,
    computed_for_window DATERANGE  NOT NULL,
    computed_at       TIMESTAMP    NOT NULL DEFAULT NOW(),
    PRIMARY KEY (horizon, "window", segment_type, segment_value)
);
