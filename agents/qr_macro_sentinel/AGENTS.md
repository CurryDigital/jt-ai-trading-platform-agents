# AGENTS.md — qr_macro_sentinel

## Boot Sequence
1. Read MEMORY.md for known macro patterns and recurring events
2. Read .learnings/MACRO_EVENTS.md for event history

## On HEARTBEAT (every 2 hours)

### Step 1: Scan for market-moving events

Search the web using Brave for recent macro news. Rotate queries:
- "market moving news today"
- "Trump trade policy tariff latest"
- "Federal Reserve interest rate decision"
- "OPEC oil production meeting"
- "China economic data PMI"
- "cryptocurrency regulation SEC"
- "geopolitical tension conflict"

### Step 2: Assess each significant finding

For each event detected:
1. What asset classes are affected? (equities, crypto, FX, commodities)
2. What is the expected direction? (bullish, bearish, neutral)
3. Is there historical precedent in our data?
4. Confidence level (low/medium/high)?

### Step 3: Log to .learnings/MACRO_EVENTS.md

```markdown
## [MACRO-YYYYMMDD-XXX] event_type

**Date:** YYYY-MM-DD
**Event:** Brief description
**Affected assets:** XLI, SMH, GLD, ...
**Expected impact:** Bearish industrials, bullish gold
**Historical precedent:** Similar event in 2018 caused X% move
**Confidence:** high | medium | low
**Status:** pending

### Actual outcome (fill in later)
- Asset: XLI, 2-day return: -3.2%
- Asset: GLD, 2-day return: +1.5%
```

### Step 4: Generate hypothesis (high-confidence events only)

If confidence = high AND clear historical precedent:

Create an idea spec and insert into the pipeline:
```sql
INSERT INTO openclaw_researcher.strategy_workflow
  (strategy_id, name, status, experiment_id, assigned_by)
VALUES ('{uuid}', 'macro_{event_type}_{date}', 'pending', '{exp_id}', 'qr_macro_sentinel');

INSERT INTO openclaw_researcher.events
  (event_type, strategy_id, payload_json, source_agent, domain)
VALUES ('experiment.started', '{strategy_id}',
  '{"experiment_id":"{exp_id}","strategy_type":"geopolitical_event",
    "description":"...","hypothesis":"...","macro_context":{...}}',
  'qr_macro_sentinel', 'quant');
```

Hub will route to qr_data_validator on next heartbeat.

### Step 5: Review past predictions

Every 4th heartbeat, check accuracy of past macro event predictions:
```sql
SELECT * FROM openclaw_researcher.macro_events
WHERE actual_impact IS NULL AND event_date < CURRENT_DATE - 3;
```

For each, query gold layer to compute actual price impact and update.
If prediction was correct → boost confidence for similar events.
If wrong → log miscalibration to .learnings/LEARNINGS.md.

## Promotion rules
- Same event pattern seen 3+ times with consistent impact → promote to MEMORY.md as a "macro rule"
- Example: "Trump tariff speech → XLI drops 2-4% in 2 days" (confirmed 3x)
