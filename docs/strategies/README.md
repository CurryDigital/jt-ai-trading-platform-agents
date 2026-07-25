# Strategy documentation

**Rule: every strategy has exactly one `<strategy_id>.md` here**, documenting
its overview AND the exact buy-signal pipeline. This is the single place a
human (or the next agent) can learn what a strategy does and how its BUY is
computed, without reverse-engineering scattered SQL and Python.

Why this exists: signal generation is spread across three mechanisms (DB
criteria, dedicated calculators, ingested research files). Without a per-
strategy doc, "how does strategy X actually decide to buy?" has no answer you
can trust — which is exactly how MACD signals stayed silently dead (NULL
`macd_histogram`) and how strategies ended up all-HOLD with nobody noticing.

## The two kinds of doc

- **`source: authored`** — the strategy's logic lives in *code* (a dedicated
  calculator like `s9_macd_daily.py` / `calc_etf_relative_momentum.py`, or a
  signal-agent class in `agents/signals/strategies/`). A human writes the doc
  by reading that code; it is the authoritative description. The generator
  never overwrites these.
- **`source: generated`** — the strategy's logic lives in *data*
  (`gold.strategy_registry.signal_logic` / `.exit_logic`, criteria rows, or an
  ingested signal file). `tools/gen_strategy_docs.py` produces the doc from the
  DB so it can't drift. Enrich the prose, keep the generated blocks.

## Tooling

- `tools/gen_strategy_docs.py` — reads `gold.strategy_registry` (+ criteria +
  latest `strategy_backtest_runs`) and writes/refreshes a `generated` doc for
  every strategy that doesn't already have an `authored` one. Run it after
  onboarding a strategy. (Needs DB access — operator/hermes runs it.)
- `tools/check_strategy_docs.py` — CI. Fails if a strategy that is
  offline-knowable (the signal-agent `registry.json` ids) has no doc, and — when
  a DB is reachable — if any `gold.strategy_registry` strategy has no doc, or a
  doc exists for a strategy that no longer exists (orphan).

## Template
See `_TEMPLATE.md`. The **Buy-signal pipeline** section is mandatory and must be
exact enough to recompute today's signal by hand.
