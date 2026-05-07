# LEARNINGS.md — qr_macro_sentinel Calibration & Miscalibration Log

_Starts empty. Audit cycle findings and calibration issues are logged here._

## Format

```
- [YYYY-MM-DD] {severity}: {issue_description}
  - Affected predictions: {event_type} on {date}
  - Expected vs Actual: {expected} vs {actual}
  - Action taken: {adjustment}
```

Severity levels:
- `INFO` — Minor drift, within tolerance
- `WARNING` — Notable miscalibration, threshold adjustment needed
- `CRITICAL` — 5+ wrong predictions in a row, major recalibration required

---

## Calibration History

_No calibration entries yet._

---

_Last updated: 2026-04-29 (initial creation)_
