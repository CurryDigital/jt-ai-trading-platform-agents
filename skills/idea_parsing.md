# Skill: Idea Parsing

## Purpose
Defines how the Idea Intake agent converts free-text trading ideas
into valid param_sets. Covers shorthand expansions, defaults,
ambiguity resolution, and hard limits before queuing.

Load this skill: Idea Intake agent only.

---

## Parse order (always follow this sequence)

1. Extract strategy_type (required — ask if missing)
2. Extract asset_universe (required — ask if missing)
3. Extract date_range (default to last 3 years if missing)
4. Extract numeric params (default from strategy_type table if missing)
5. Apply hard limits (duplicate check, flood control)
6. Confirm and queue

---

## Strategy type keywords

| User says | Normalise to |
|-----------|-------------|
| momentum, trend, trending | `momentum` |
| mean reversion, mean-reversion, reversion, reversal | `mean_reversion` |
| breakout, break out, breakout trading | `breakout` |
| pairs, pair trading, stat arb, statistical arbitrage | `pairs` |
| trend following, trend-following | `trend` |

If none match, ask: "What type of strategy — momentum, mean_reversion, breakout, or pairs?"

---

## Asset universe shorthands

| User says | Expands to |
|-----------|-----------|
| tech stocks, tech | AAPL, MSFT, GOOGL, NVDA, META, AMZN |
| large cap, large-cap | AAPL, MSFT, GOOGL, AMZN, NVDA, META, BRK-B, JPM, JNJ, V |
| S&P 500, sp500, s&p | Top 20 by market cap proxy (see agent) |
| crypto | BTC-USD, ETH-USD, SOL-USD, BNB-USD |
| hk stocks, hkex, hong kong | 0700.HK, 0005.HK, 0941.HK, 1299.HK, 0388.HK |
| faang, faamg | META, AAPL, AMZN, NVDA, GOOGL |
| banks, financials | JPM, BAC, WFC, GS, MS |
| energy | XOM, CVX, COP, SLB, EOG |

Explicit tickers: match uppercase 2–5 character strings (A-Z, optional hyphen + suffix)
Noise filter: skip I, A, US, UK, HK, ETF, IPO, OOS, QA, IS

---

## Numeric parameter defaults by strategy type

| strategy_type | lookback_window | entry_threshold | exit_threshold |
|---------------|----------------|----------------|----------------|
| momentum | 20 | 1.5 | 0.5 |
| mean_reversion | 20 | 2.0 | 0.5 |
| breakout | 14 | 1.0 | 0.3 |
| pairs | 30 | 2.0 | 0.5 |
| trend | 50 | 1.5 | 0.5 |

Apply these only if the user has not specified the value.
When defaulting, include the defaults in the confirmation message.

---

## Date range parsing

| User says | Resolves to |
|-----------|------------|
| last N years | start = today - N years, end = yesterday |
| last year / recent | start = today - 1 year, end = yesterday |
| 2022–2024 (two years) | start = 2022-01-01, end = 2024-12-31 |
| single year (2023) | start = 2023-01-01, end = 2023-12-31 |
| (nothing) | start = today - 3 years, end = yesterday |

---

## Confirmation format

Always confirm before queuing with this exact format:
```
Queued: {strategy_type} on [{ticker1}, {ticker2}, +N more], {start} → {end}.
Lookback: {N}d, entry: {x}, exit: {y}. Experiment ID: {uuid}
```

If any params were defaulted, note them:
```
Queued: momentum on [AAPL, MSFT, GOOGL], 2022-01-01 → 2024-12-31.
Lookback: 20d (default), entry: 1.5 (default), exit: 0.5 (default).
Experiment ID: abc-123
```

---

## Hard limits (check before queuing)

### Duplicate check
Query events WHERE event_type = 'experiment.started'
AND created_at >= NOW() - INTERVAL '30 days'
AND param_set matches exactly (compare sorted JSON)

If match found:
> "This param_set ran {N} days ago. Change strategy_type, assets, or date range to make it distinct."

### Flood control
Query agent_work_queue WHERE status = 'in_progress'
If count ≥ 10:
> "Pipeline busy: {N}/10 slots in use. Try again once some complete."

---

## One clarifying question rule

If strategy_type AND asset_universe are both missing → ask one question covering both.
If only one is missing → ask one question about that field only.
Never ask more than one question per message.
Never ask about optional fields (lookback, thresholds, date_range) — default them.

---

## Status query keywords

Trigger a pipeline status report when user says:
status, what's running, pipeline status, how many, in progress,
experiments, what's happening, any updates, summary
