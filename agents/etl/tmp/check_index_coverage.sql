SELECT
    ticker,
    MAX(date) AS latest_date,
    COUNT(*) AS days
FROM gold.index_metrics
WHERE ticker IN ('^GSPC','^IXIC','^DJI','^RUT','^HSI')
GROUP BY ticker
ORDER BY ticker;
