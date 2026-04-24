# LEARNINGS.md — qr_etl_manager
# Corrections, knowledge gaps, best practices discovered
# Format: [YYYY-MM-DD] What was learned + why it matters

---

## Log Entry Template
```
[YYYY-MM-DD HH:MM UTC] <Category>: <Brief title>
- **Discovery**: What was learned or corrected
- **Source**: User correction, failed attempt, docs, research
- **Impact**: How this changes future behavior
- **Promote To**: Which file should capture this permanently
```

---

## Tool Usage Patterns

_None logged yet._

## Data Source Patterns

_None logged yet._

## SQL/Database Patterns

_None logged yet._

## User Preferences

_None logged yet._

[2026-04-22 01:39 UTC] ETL Coverage Gap: Strategies Tab APIs vs Pipeline
- **Context**: Operator asked if strategies tab APIs are covered by ETL refreshing pipelines. Reviewed all API endpoints and ETL scripts.
- **Discovery**:
  - ETL pipeline covers: bronze→silver→gold→consumption for command/lab/market/performance/portfolio tabs
  - consumption.strategies_signals_current: DOES NOT EXIST — but deploy-auto and performance/strategy endpoints query it
  - consumption.portfolio_positions_current: EXISTS but 0 rows — daily-pnl endpoint reads from it
  - gold.strategy_equity_curve: EXISTS but 0 rows — needed for performance curves
  - No `consumption/strategies/` directory exists in ETL pipeline
  - No consumption view builder for strategy signals exists
- **Impact**: Strategies tab APIs work because they query gold tables directly, but consumption layer views (signals_current, positions_current) are empty/missing. This means deploy-auto can't find BUY signals and daily-pnl returns empty.
- **Promote To**: TOOLS.md — document which APIs need which consumption views; AGENTS.md — add strategies tab to consumption refresh pipeline
- **Status**: Needs ETL script creation for consumption/strategies/ directory
