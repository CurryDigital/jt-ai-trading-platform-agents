# Event Contracts — Timeout Thresholds

| Stage | Waiting for | Timeout |
|---|---|---|
| `experiment.started` | `dataset.ready` | 15 min |
| `dataset.ready` | `backtest.completed` | 10 min |
| `backtest.completed` | `risk.evaluated` | 30 min |
| `risk.evaluated` | `qa.validated` | 5 min |
| `qa.validated` | `qr_exp_manager` ack | 5 min |

Source of truth: matches TOOLS.md exactly.
