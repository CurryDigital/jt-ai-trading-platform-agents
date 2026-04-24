# HEARTBEAT.md — qr_data_validator

You are woken up every 3 minutes. YOU MUST use your database execution tool to run the following exact SQL query:

```sql
SELECT * FROM openclaw_researcher.v_qr_data_validator_work order by created_at DESC LIMIT 10;