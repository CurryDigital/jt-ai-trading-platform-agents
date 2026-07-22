SELECT sym, name, region, last, change_pct,
       change_1d, change_1w, change_1m, change_ytd,
       est_1d, est_1w, est_1m,
       spark IS NOT NULL AS has_spark,
       updated_at
FROM consumption.dashboard_indices
ORDER BY region, sym;
