<!-- REVIEWED: 2026-04-28 09:09 UTC — Daily learning summary completed -->
[2026-04-16 03:15 UTC] ETL Refresh Completed (Partial Success)
- **Context**: Full daily_refresh.sh executed
- **Root Cause**: FMP API rate limits (403), crypto silver missing, SQL window function errors
- **Resolution**: Bronze/silver/gold/consumption all ran. Core equity data successful.
- **Prevention**: Add FMP retry/backoff; fix crypto silver pipeline; fix FX/commodity SQL

<!-- REVIEWED: 2026-04-28 09:09 UTC — Daily learning summary completed -->
[2026-04-16 01:20 UTC] API Timeout: FMP ingestion failed on connection timeout
- **Context**: Running bronze/fmp/ingest_fmp.py during daily refresh
- **Root Cause**: FMP API rate limit exceeded (503 response)
- **Resolution**: Added 30s retry with exponential backoff
- **Prevention**: Check rate limits before batch calls; implement circuit breaker
