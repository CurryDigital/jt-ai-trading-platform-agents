# HEARTBEAT.md — qr_etl_manager
Run daily refresh: lock gold_layer_state, execute bronze→silver→gold→consumption scripts,
unlock gold_layer_state, emit etl.completed/partial/failed.
If already refreshed today: HEARTBEAT_OK
