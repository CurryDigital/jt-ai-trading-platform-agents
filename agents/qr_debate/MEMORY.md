# MEMORY.md — qr_debate

## Lessons Learned (Updated: 2026-04-28 14:00 UTC)

### 24-Hour Summary (Apr 28)
**4 debates processed.** All 4 strategies were auto-rejected via fail-fast path (`risk_approved=false`).

**Critical Finding: Broken Lineage Learning**
- All 4 strategies are from the **same "Mega-Cap Capitulation Rebound" HSI mean reversion lineage**
- Generations 1→2→3→4 all have **identical failure mode**: concentration_risk (0.35 > 0.25) + low_trade_count (15 < 30)
- **Same metrics across all 4 generations**: Sharpe 1.2 IS / 0.9 OOS, 52% win rate, 12.5-day hold, 35 IS trades / 15 OOS trades
- The strategy generator is **not learning from risk feedback** — it's producing carbon copies with the same fatal flaws

**Risk Flag Patterns (Apr 28)**
| Flag | Count | % of Total |
|------|-------|------------|
| `concentration_risk` | 4/4 | 100% |
| `low_trade_count` | 4/4 | 100% |

**Key Insight**: This is not a strategy quality problem — it's a **generator feedback loop failure**. The experiment manager (qr_exp_manager) is not reading `risk.evaluated` outcomes to adjust parameters. Four generations of identical rejections proves the lineage is stuck.

**Immediate Action Required**:
1. **Cap this lineage at Generation 4** — no further children allowed
2. **Fix qr_exp_manager** — must read risk feedback and adjust max_single_asset_exposure < 0.25, trade_count_oos > 30
3. **Add lineage penalty** — if N consecutive generations have identical risk flags, auto-reject before backtest

### 7-Day Pattern Analysis (Apr 11–Apr 28)

#### (1) Common Failure Modes Across Rejected Strategies
- **100% auto-rejected via fail-fast path** — All 9 strategies in the last 7 days had `risk_approved=false`
- **Primary failure mode: `low_sharpe_oos`** — Every single strategy had OOS Sharpe < 0.5 (range: 0.14–0.99, but mostly 0.15–0.26)
- **Secondary failure: `overfitting_signal`** — 8 of 9 strategies flagged for IS/OOS degradation
- **Tertiary failure: `low_trade_count`** — 3 strategies had insufficient sample sizes (< 5 trades)
- **Extreme outlier returns detected** — Strategy `a044d22d` showed -37.66% IS → +3609% OOS (negative IS/OOS ratio -0.12), indicating catastrophic signal inversion
- **Win rates consistently below random** — Range 20.9%–41.7%, averaging ~31%. This is worse than a coin flip.

#### (2) Borderline Strategies (Promise but Failed)
- **Strategy `135e3140` (NVDA breakout)**: OOS Sharpe 0.99, returns 1012% — BUT only 5 total trades. High promise, no statistical validity.
- **Strategy `f30cb8da` (volatility term structure)**: IS/OOS ratio 0.89 (excellent preservation), but Sharpe only 0.20. Stable but no edge.
- **Strategy `02010e4e` (NVDA breakout)**: OOS Sharpe 0.99, returns 1012% — BUT only 6 trades. Same pattern as above.

**Pattern**: Strategies with OOS Sharpe > 0.5 exist but are killed by `low_trade_count`. The risk system is correctly conservative here.

#### (3) Risk Flag Patterns
| Flag | Count | % of Total |
|------|-------|------------|
| `low_sharpe_oos` | 9/9 | 100% |
| `overfitting_signal` | 8/9 | 89% |
| `low_trade_count` | 3/9 | 33% |

**Key insight**: The `low_sharpe_oos` flag is universal. No strategy in the last 7 days achieved viable risk-adjusted returns. This suggests either:
- The strategy generation pipeline is producing fundamentally flawed strategies
- The market regime (2023–2026) is particularly hostile to the tested signals
- The Sharpe threshold (0.5) may be too high for the current generation quality

#### (4) Recommendations for Future Strategy Generation

**Immediate (next 30 days):**
1. **Raise the floor on strategy generation** — Current strategies are consistently failing at Sharpe 0.5. Consider requiring a minimum IS Sharpe > 0.3 before even running OOS tests.
2. **Address the win rate problem** — 31% average win rate is worse than random. This suggests the entry/exit logic is inverted or the signal is noise. Review the signal generation logic in `qr_researcher`.
3. **Fix the extreme outlier returns** — Strategies showing 3000%+ annual returns with 0.25 Sharpe indicate leverage blowup or data errors. Add a sanity check: if annual returns > 500%, auto-reject before risk evaluation.

**Medium-term (next 90 days):**
4. **Diversify strategy types** — 100% of recent strategies are momentum/breakout/mean reversion. Consider adding: trend-following, statistical arbitrage, or options-based strategies.
5. **Review the 20-day lookback** — Multiple strategies use 20-day lookback with 16-day avg hold. This is nearly random noise. Consider longer lookbacks (60–120 days) for more robust signals.
6. **Fix the exit threshold problem** — Multiple strategies use exit -0.01 (pathologically tight). This causes excessive turnover and erodes returns. Consider dynamic exits based on ATR or volatility.

**Long-term (next 180 days):**
7. **Add a pre-debate sanity gate** — If `risk_approved=false` AND `sharpe_oos < 0.3`, skip debate entirely (already implemented via fail-fast). But consider adding a "borderline" path for `0.3 < sharpe_oos < 0.5` with abbreviated debate.
8. **Track lineage degradation** — Generation 3 strategies are showing consistent IS/OOS degradation (~0.6 ratio). Consider capping generations at 2 or adding lineage penalty.

### Historical Context
- **Best strategy processed**: `87cda947` (RSI mean reversion, tech large cap) — conviction 0.78, OOS Sharpe 1.92, 3.83% DD. This was a Generation 1 strategy with anti-overfitting design.
- **Worst strategy processed**: `test-v6-1775567740` — catastrophic -127% drawdown, zero IS/OOS ratio. Correctly rejected.
- **Calibration status**: Conviction scores have been honest (0.05–0.78 range). No cases of conviction > 0.5 for risk-rejected strategies. Fast-fail invariant holds.

### Next Review
Scheduled: 2026-04-30 14:00 UTC

### Critical Process Failure (2026-04-28)

**Issue**: AGENTS.md Section "FINAL STEP: THE WAKE-UP PING" mandates calling `sessions_send` to `agent:qr_hub:main` immediately after every `debate.completed` INSERT to wake the Hub for event routing. This step has been consistently missed in all prior debates.

**Impact**: 
- Hub remains unaware of completed debates until its next scheduled poll
- Debate completion events sit in `events` table unprocessed
- Pipeline latency increases by up to the Hub's polling interval
- qr_qa may proceed without seeing debate telemetry

**Root Cause**: 
- The `sessions_send` requirement is at the bottom of AGENTS.md, after the SQL blocks
- Natural workflow ends at Step 8 (INSERT event_processing) — the ping is visually separated
- No automated check or reminder exists to enforce this step
- Previous implementations focused on SQL operations and neglected the cross-session wake protocol

**Fix Applied**:
1. Added explicit `sessions_send` call after `debate.completed` emission
2. Updated this MEMORY.md entry as permanent reminder
3. Will verify on next debate that Hub receives wake notification

**Verification**: After next `debate.completed`, check that `agent:qr_hub:main` receives the wake message and polls `v_pending_events` within seconds.

### Critical Lineage Failure (2026-04-28)

**Issue**: "Mega-Cap Capitulation Rebound" HSI mean reversion strategy produced 4 consecutive generations (Gen 1→4) with **identical failure mode**: concentration_risk (0.35 > 0.25) + low_trade_count (15 < 30).

**Impact**:
- Wasted compute on 4 backtests with identical outcomes
- No learning from risk feedback in experiment manager
- Pipeline clogged with non-viable lineage

**Root Cause**:
- qr_exp_manager does not read `risk.evaluated` outcomes to adjust parameters
- No lineage cap or penalty mechanism exists
- Generator optimizes for Sharpe, not risk-adjusted viability

**Fix Required**:
1. Cap lineage at Generation 2 if identical risk flags persist
2. Add pre-backtest risk parameter validation
3. Instruct generator to reduce exposure < 0.25, increase min trades > 30

---

_Updated by qr_debate daily cron job.

