# BOOTSTRAP.md - qr_hub First Run

Hub does not have a discovery conversation. It has a checklist.

## On first run, complete these steps in order:

### 1. Confirm workspace files exist
- [ ] `IDENTITY.md` — present
- [ ] `SOUL.md` — present
- [ ] `TOOLS.md` — present and filled in with real DB/path values
- [ ] `HEARTBEAT.md` — present
- [ ] `MEMORY.md` — create empty file if missing
- [ ] `USER.md` — present and filled in by operator

### 2. Confirm DB connectivity
Run `SELECT 1` against RDS. If this fails, do not proceed. Log CRITICAL and wait.

### 3. Load routing table
Load `hub/router.py → ROUTING_TABLE`. Merge with `routing_rules` DB table.
Log the full merged routing table at INFO level on first boot only.

### 4. Check for event backlog
```sql
SELECT COUNT(*) FROM v_pending_events
```
If > 0: log INFO "Starting with N pending events — processing now."

### 5. Write startup record
Insert into `workflow_events`: `{ agent: qr_hub, event: session_start, ts: now() }`

### 6. Begin dispatch loop
Poll `v_pending_events` every `HUB_POLL_INTERVAL_SECONDS` seconds.

---

## When you're done

Delete this file. Hub is running. It does not need a bootstrap script anymore.