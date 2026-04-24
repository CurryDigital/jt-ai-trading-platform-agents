# HEARTBEAT.md — qr_exp_manager
Nightly cycle (if hour=16 UTC): query strategy_lineage for top performers,
generate 5 variants from best. If no recent lineage, seed 3 random.
All other heartbeats: check in-progress count, log if near flood limit.
If not nightly hour and count OK: HEARTBEAT_OK
