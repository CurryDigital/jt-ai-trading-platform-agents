# near_golden/ — OOS-validated, pending approval

Mirrors `gold.strategy_registry.priority = 'NEAR_GOLDEN'`.

A strategy moves here from `../experimental/` only after real out-of-sample
backtest results exist for it (sharpe_oos / win_rate_oos / max_drawdown_oos
populated in `gold.strategy_registry` from `gold.strategy_backtests`).

Promotion mechanics: `git mv` the file, update `tier` + `class_path` in
`../registry.json`, update the DB row's `priority` — one commit. The registry
loader rejects any entry whose tier doesn't match its folder.
