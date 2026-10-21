-- Remediation: correct HK asset_class mislabels and populate missing descriptions
-- in gold.strategy_registry so the Strategy Lab UI no longer needs a ticker-suffix
-- workaround in backend/app/routes/strategies.py.
--
-- Affected strategies: any published registry row whose universe contains .HK tickers.

BEGIN;

-- 1. Correct asset_class for all HK-listed strategies currently mis-tagged as US Stock.
UPDATE gold.strategy_registry
SET asset_class = 'HK / Asian Equities',
    updated_at  = NOW()
WHERE universe_tickers IS NOT NULL
  AND EXISTS (SELECT 1 FROM unnest(universe_tickers) t WHERE t LIKE '%.HK')
  AND asset_class != 'HK / Asian Equities';

-- 2. Populate missing descriptions, signal_logic and exit_logic for HK low-volatility strategies.
UPDATE gold.strategy_registry
SET description = 'Hong Kong weekly low-volatility equity strategy: ranks Hang Seng tickers by realised volatility and holds the lowest-volatility names, rebalancing daily to target weights.',
    signal_logic = 'entry_basis=next_open;weights_are_target_portfolio=True',
    exit_logic   = 'Weekly rebalance with 5-trading-day signal lag. Selects the 5 HK stocks with the lowest 63-day realized volatility; full rebalance replaces positions at the next signal.',
    updated_at  = NOW()
WHERE strategy_id = 'HK_LowVol_Weekly';

UPDATE gold.strategy_registry
SET description = 'Hong Kong weekly low-volatility equity strategy with a market trend filter: holds low-volatility Hang Seng tickers only when a broader market trend filter is positive, rebalancing daily to target weights.',
    signal_logic = 'entry_basis=next_open;weights_are_target_portfolio=True',
    exit_logic   = 'Weekly rebalance with 5-trading-day signal lag. Selects the 5 HK stocks with the lowest 63-day realized volatility; moves to 100% 2800.HK when 2800.HK 126-day total return is negative.',
    updated_at  = NOW()
WHERE strategy_id = 'HK_LowVol_TrendFilter_Weekly';

COMMIT;

-- 3. Verify acceptance criteria.
SELECT strategy_id,
       asset_class,
       array_length(universe_tickers, 1) AS universe_size,
       description IS NULL               AS desc_null,
       priority,
       status
FROM   gold.strategy_registry
WHERE  priority IN ('EXPERIMENTAL', 'NEAR_GOLDEN', 'GOLDEN')
  AND  status NOT IN ('rejected', 'retired', 'DEPRECATED')
  AND  (description IS NULL OR asset_class IS NULL)
ORDER BY strategy_id;
