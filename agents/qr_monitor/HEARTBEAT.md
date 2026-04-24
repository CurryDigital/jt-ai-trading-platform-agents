# HEARTBEAT.md — qr_monitor
Scan v_monitor_overview for stuck workflows per timeout thresholds.
Check for orphaned events with no event_processing rows.
If breached: log and emit workflow.stuck.
If all clear: HEARTBEAT_OK
