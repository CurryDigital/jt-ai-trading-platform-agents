# Skill: Risk Framework

## Purpose
Defines how the Risk agent evaluates a completed backtest, what
thresholds it loads from risk_config, how it scores and flags a
strategy, and when to approve vs reject.

Load this skill: Risk agent only.

---

## Core principle

Risk always emits risk.evaluated — even on rejection.
QA cannot run without a risk.evaluated event.
Never silently drop an evaluation.

---

## Thresholds (loaded from risk_config at runtime, not hardcoded)

| threshold_name | operator | default value | meaning |
|----------------|----------|---------------|---------|
| `max_drawdown` | `<` | -0.20 | Max drawdown must not exceed -20% |
| `min_sharpe_oos` | `>` | 0.50 | OOS Sharpe must be above 0.5 |
| `min_sharpe_ratio` | `>` | 0.60 | IS/OOS Sharpe ratio must be above 0.60 |
| `high_turnover` | `<` | 2.00 | Annualised turnover must be below 200% |
| `low_trade_count` | `>` | 30 | OOS trade count must exceed 30 |
| `tail_risk` | `<` | 0.10 | CVaR (95%) must be below 10% (if available) |

Always reload from risk_config at evaluation time. Never cache thresholds
between runs — they may have been updated by the operator.

---

## Risk score calculation

Score is a float 0.0–1.0. Higher = riskier. Computed as:

```
score = weighted average of individual flag severities

weights:
  max_drawdown breach:       0.35
  sharpe_oos below min:      0.30
  sharpe_ratio below min:    0.20
  high turnover:             0.10
  low trade count:           0.05

Each flag contributes its weight × severity_multiplier:
  severity_multiplier = how_far_from_threshold / threshold (capped at 1.0)
```

A strategy that breaches no thresholds scores 0.0–0.15 (residual).
A strategy that breaches max_drawdown by 50% scores ~0.525 from that flag alone.

---

## Flag definitions

Emit any subset of these in the flags[] array:

| flag | condition |
|------|-----------|
| `high_drawdown` | max_drawdown < threshold |
| `low_sharpe_oos` | sharpe_oos < min_sharpe_oos |
| `overfitting_risk` | sharpe_ratio_is_oos < min_sharpe_ratio |
| `high_turnover` | turnover_rate > high_turnover threshold |
| `low_trade_count` | trade_count_oos < low_trade_count threshold |
| `zero_trades` | trade_count_oos == 0 (auto-reject) |
| `negative_oos` | returns_annualised_oos < 0 |

---

## Approval logic

```
approved = True  if  risk_score < 0.35  AND  no auto-reject flags
approved = False if  risk_score >= 0.35 OR   zero_trades flag present
```

Borderline (0.25–0.35): flag rather than clear.
When in doubt, reject. QA can verify; Risk cannot undo an approval.

---

## risk.evaluated payload (always emit all fields)

```json
{
  "experiment_id": "uuid",
  "strategy_id": "uuid",
  "risk_score": 0.0,
  "approved": true,
  "flags": [],
  "thresholds_used": { "max_drawdown": -0.20, ... },
  "notes": "Human-readable explanation of the decision"
}
```

The `notes` field is mandatory. Even on approval, write what was checked:
  "All thresholds clear. Drawdown -0.12, Sharpe OOS 0.87, IS/OOS ratio 0.74."

On rejection, be specific:
  "Max drawdown -0.28 exceeds threshold -0.20. Flagged: high_drawdown."

---

## strategy_workflow update

Before emitting risk.evaluated, write results to strategy_workflow:
- risk_score
- risk_flags (comma-separated flag names as text)
- risk_approved (boolean)
- risk_notes (notes text)
- risk_evaluated_at (CURRENT_TIMESTAMP)

This is the canonical record. The event payload is a notification.
