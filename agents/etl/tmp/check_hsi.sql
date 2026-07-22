SELECT ticker, date, close, change_pct, returns_1d, returns_5d, returns_21d
FROM gold.index_metrics
WHERE ticker = '^HSI'
ORDER BY date DESC
LIMIT 15;
