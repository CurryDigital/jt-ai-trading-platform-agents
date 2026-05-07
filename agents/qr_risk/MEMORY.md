# MEMORY.md — qr_risk

## Lesson Learned: 2026-04-28 — The Wake-Up Ping is MANDATORY

**What happened:** Processed events were sitting in the database but the Hub wasn't picking them up promptly because I failed to send the wake-up ping after emitting `risk.evaluated`.

**Root cause:** AGENTS.md Section "FINAL STEP: THE WAKE-UP PING" explicitly requires:
```
Immediately after you successfully execute an INSERT INTO openclaw_researcher.events 
statement, you MUST explicitly invoke your sessions_send tool to wake up the Hub 
so it can route your new event.
```

**Why this matters:**
- The Hub polls for events but relies on wake-up pings for real-time responsiveness
- Without the ping, events can sit unprocessed for minutes/hours
- Downstream agents (Debate, QA) never get triggered
- The pipeline appears "stuck" even though Risk completed its work

**Correct pattern after every risk.evaluated emission:**
1. Emit event via `INSERT INTO events ...`
2. IMMEDIATELY wake the Hub via `sessions_send` to `agent:qr_hub:main`

**Action:** Always send wake-up ping after ANY event insert. No exceptions.

## Previous Lessons

- **2026-04-10:** Drawdown math error — `-3.83%` is BETTER than `-20%`. 
  Use absolute value comparison: `abs(dd) > abs(threshold) * 100`
  Never use raw `<` comparison on negative drawdown values.

- **2026-04-09:** IAM auth disabled — must read DB_PASSWORD from `.env` 
  file directly, not generate tokens. Password auth is the current mode.

- **2026-03-22:** Notification queue files must be deleted after processing 
  to prevent duplicate work on restart.

---

## Daily Learning Summary — 2026-04-29

### Patterns Identified (Last 24 Hours)

1. **Persistent Strategy Family Failures:**
   - 4 consecutive generations of mean_reversion strategies (gen 1-4) all rejected
   - Same two flags every time: `concentration_risk` (0.35 > 0.25) and `low_trade_count` (15 < 30)
   - **Recommendation:** Upstream strategy generation needs to diversify asset exposure and increase trade frequency

2. **Consistent Low Sharpe OOS:**
   - Multiple strategies showing sharpe_oos between 0.15-0.25 (threshold: 0.50)
   - This is the most common single flag across all rejections
   - Suggests strategies are overfit to in-sample data

3. **Overfitting Signal Borderline:**
   - Several strategies with sharpe_ratio_is_oos around 0.59-0.60 (threshold: 0.60)
   - Barely missing the threshold — indicates calibration might need review

### Actions Taken

- ✅ Fixed wake-up ping workflow (now sending sessions_send after every event)
- ✅ Documented drawdown math correction in MEMORY.md
- ✅ Set up daily learning summary cron job (18:00 UTC = 2am HKT)

### Recommendations for Pipeline

1. **Threshold Review:** Consider whether 0.60 overfitting threshold is too strict for mean_reversion strategies
2. **Concentration Check:** Add pre-flight check in strategy generation to enforce max 25% single asset exposure
3. **Trade Count Minimum:** Ensure backtest periods are long enough to generate ≥30 OOS trades
4. **Wake-Up Ping:** All agents should adopt this pattern for real-time event routing

### Statistics (Last 7 Days)

| Metric | Count |
|--------|-------|
| Total Events Processed | ~30 |
| Approved | 1 (strategy 87cda947 — after manual correction) |
| Rejected | ~29 |
| Most Common Flag | low_sharpe_oos |
| Second Most Common | overfitting_signal |

---
