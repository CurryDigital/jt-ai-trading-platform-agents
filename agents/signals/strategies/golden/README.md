# golden/ — approved strategies

Mirrors `gold.strategy_registry.priority = 'GOLDEN'`.

Empty is the honest state: no signal-agent strategy has yet passed the full
promotion path (OOS backtest gates → near_golden → approval → golden).
The "golden" strategies visible on the frontend today are DB registry rows
whose signals are produced elsewhere (ETF paper-signal ingestion, S9 MACD in
`agents/etl/gold/strategy/`), not implementations in this folder.

To promote a strategy here: `git mv` its file from `../near_golden/`, update
`tier` + `class_path` in `../registry.json`, and update the DB row's
`priority` — one commit. The registry loader rejects any entry whose tier
doesn't match its folder.
