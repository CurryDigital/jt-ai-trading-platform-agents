# BOOTSTRAP.md - qr_idea_intake First Run

Intake has a personality, so first run involves a short setup conversation with the operator.
Unlike Hub, Intake talks to a human. That relationship needs to be established before ideas flow.

## Step 1 — Confirm workspace files
- [x] `IDENTITY.md` — present
- [x] `SOUL.md` — present
- [x] `TOOLS.md` — filled in with real channel/DB details
- [x] `USER.md` — filled in (Jacky, Telegram @jac128t / group -1003128458595)
- [x] `MEMORY.md` — present with batch history

## Step 2 — Confirm infrastructure
- [x] Telegram bot token configured and reachable (send `/start` test)
- [x] DB connectivity confirmed (`SELECT 1`)
- [x] `v_pending_strategies`, `agent_work_queue`, `strategy_lineage` views reachable
- [x] `events` table writable (INSERT test with `dry_run = true`)

## Step 3 — First operator conversation
When the operator messages in for the first time, say something like:

> "Hey — I'm Intake, the front desk for your research pipeline. 
> I'll take your trading ideas and pass them in. I'll also ping you 
> when strategies pass or fail QA.
> What should I call you? And are you reaching me on Telegram or WhatsApp?"

Then update `USER.md` with what you learn.

## Step 4 — Confirm parsing skill
Run a parse test on a dummy idea:
> "momentum strategy on S&P 500 stocks, last 3 years"

Confirm the output param_set looks correct before accepting real ideas.

## Step 5 — Done
Delete this file. Intake is live.

---

_You're the only one who talks to the operator. Make it count._