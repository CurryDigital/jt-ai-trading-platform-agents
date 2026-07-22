SELECT
    ticker, date, close, change_pct, ytd_change,
    returns_1d, returns_5d, returns_21d, returns_63d
FROM gold.index_metrics
WHERE ticker IN ('^GSPC','^IXIC','^RUT','^HSI')
ORDER BY ticker, date DESC
LIMIT 20;
