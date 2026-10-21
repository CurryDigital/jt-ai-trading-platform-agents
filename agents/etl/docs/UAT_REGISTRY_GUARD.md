# UAT Registry Guard (kanban t_9bee1ba6)

End-of-day guard: DUP825942 (PAPER_UAT book) vs gold.strategy_registry.
Successor of the qr_research 4-hourly live-API guard (retired by qr_research
once this is live) and of scripts/uat_registry_crosscheck.py (t_a44c50e1,
paused 2026-09-26, superseded).

## Where it runs

- `audit/uat_registry_guard.py` — step 7 of `scripts/yf_us_postclose_topup.sh`
  (22:30 UTC Mon-Fri), after the step-6 PAPER_UAT mirror sync. NON-FATAL:
  its exit code never fails the top-up.
- `audit/uat_guard_watchdog.py` via `scripts/uat_guard_watchdog.sh` — cron
  `qr_etl.uat_guard_watchdog` (79b716dae2e9, 23:45 UTC Mon-Fri,
  deliver=telegram, no_agent). Empty stdout = silent. Alerts on VIOLATION,
  ERROR, and ABSENT (guard did not run -> deadman coverage).

## Verdict contract

- exit 0 = guard RAN. verdict OK (silent) or VIOLATION (alert on stdout).
- exit 2 = ERROR/DEAD (stale mirror, DB down, exception). Distinct from
  VIOLATION so a broken guard is never confused with a healthy alert.
- Outputs: `~/.hermes/profiles/qr_etl/logs/uat_registry_guard.jsonl` +
  `uat_registry_guard_latest.json` + gold.agent_events
  (`UatRegistryGuardVerdict`).

## Checks

0. MIRROR_FRESH — positions snapshot < 3h old, else ERROR (this replaces the
   qr_research script's data:null crash: a disconnected UAT session fails the
   mirror sync, the snapshot goes stale, and the deadman catches a clean
   ERROR instead of a traceback).
a. ORPHAN_POSITIONS / UNIVERSE_VIOLATION — holdings vs active PAPER_UAT
   sleeves and their universes.
b. UNOWNED_SHORT — qty<0 with no short-permitted sleeve. Permission =
   gold.strategy_configs `allow_short=true` (none today => any short flags).
c. UNTAGGED_FILL (13h window) / UNTAGGED_ORDER (gold.ibkr_orders, same UTC
   date) — NULL/empty order_ref or strategy_id. Exempt (single-use,
   user-approved reconciliation covers): order_ref `RECON_FLATTEN_t_7d69ab61`
   (2026-10-09) and `RECON_FLATTEN_t_72843934` (2026-10-15), strategy_id
   `OPS_RECON`.
   FOREIGN_FILL — attributed to a non-active-PAPER_UAT strategy.
d. ORPHAN_OPEN_ORDER — working orders with no owning sleeve/universe.
   MULTI_PAPER_UAT — >1 active PAPER_UAT sleeve.

## Replay

`--replay-fixture <json>` injects run_ts/mirror_synced_at/positions/fills/
open_orders/ibkr_orders (registry/short-permissions default to live).
Acceptance fixture for the 2026-09-28 EOD short book lives in the t_9bee1ba6
workspace; replay flags ORPHAN_POSITIONS + UNOWNED_SHORT + UNTAGGED_FILL
(orders 14/16/18/20) exactly.

Tunables (env): UAT_GUARD_MIRROR_MAX_AGE_H (3), UAT_GUARD_FILL_LOOKBACK_H
(13), UAT_GUARD_LOG_DIR.
