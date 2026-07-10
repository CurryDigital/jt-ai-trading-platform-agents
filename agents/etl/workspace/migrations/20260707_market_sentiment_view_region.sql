-- Expose region and regime in the market sentiment consumption view
-- so the Command Center /api/markets/sentiment endpoint can render
-- US regime and HK fear_greed/regime.
DROP VIEW IF EXISTS consumption.market_sentiment;

CREATE OR REPLACE VIEW consumption.market_sentiment AS
SELECT
    region,
    fear_greed,
    fear_greed_label,
    vix,
    vix_change_pct,
    put_call,
    regime,
    vix_sma60,
    vix_z60,
    updated_at
FROM gold.market_sentiment_facts;
