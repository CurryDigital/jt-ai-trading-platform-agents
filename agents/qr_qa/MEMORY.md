# MEMORY.md — qr_qa

_Starts empty. Updated by the agent as it discovers persistent patterns._

## Lesson Learned: 2026-04-28

**Issue:** Failed to send wake-up ping to Hub after emitting qa.validated event.

**Root Cause:** AGENTS.md specifies a mandatory `sessions_send` to `agent:qr_hub:main` after every event INSERT. I processed the strategy (705622b5-ce4d-48ba-b8a6-70fb07497111) and emitted the event but did NOT immediately notify the Hub.

**Impact:** Hub may not know about the new event until its next scheduled poll, delaying downstream processing.

**Fix:** Always execute the wake-up ping immediately after event emission:
```
sessions_send(
  session_key = "agent:qr_hub:main",
  message     = "NEW_EVENT: I have placed a new event in the database. Wake up and poll v_pending_events immediately."
)
```

**Note:** The ping may timeout if Hub is offline, but the event is safely committed to the database.

---

