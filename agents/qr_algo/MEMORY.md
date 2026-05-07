# MEMORY.md — qr_algo

_Starts empty. Updated by the agent as it discovers persistent patterns._

---

## 2026-04-28 — Database Connection Fix (CRITICAL)

**NEVER hardcode `host='localhost'` in psycopg2.connect().**

The database is AWS RDS, not localhost. Always parse ALL connection variables from `/home/ubuntu/.openclaw/.env`:

```python
env_vars = {}
with open('/home/ubuntu/.openclaw/.env') as f:
    for line in f:
        if '=' in line and not line.startswith('#'):
            key, val = line.strip().split('=', 1)
            env_vars[key] = val

DB_HOST = env_vars.get('DB_HOST')        # e.g. openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com
DB_PORT = int(env_vars.get('DB_PORT', '5432'))
DB_NAME = env_vars.get('DB_NAME')        # e.g. aitrading
DB_USER = env_vars.get('DB_USER')        # e.g. openclaw_user
DB_PASSWORD = env_vars.get('DB_PASSWORD')

conn = psycopg2.connect(
    host=DB_HOST,
    port=DB_PORT,
    database=DB_NAME,
    user=DB_USER,
    password=DB_PASSWORD,
    sslmode='require'
)
```

**Previous failure:** Hardcoded `host='localhost'` caused `Connection refused` because the DB is on RDS.
**Lesson:** Always parse all connection params from .env, never assume localhost.

---

## 2026-04-28 — psycopg2 jsonb Returns Python dict Directly (CRITICAL)

When using psycopg2 with PostgreSQL jsonb columns, the returned value is ALREADY a Python dict.
**DO NOT call `json.loads()` on it** — that will raise `TypeError: the JSON object must be str, bytes or bytearray, not dict`.

**Correct:**
```python
payload = row[3]  # Already dict from psycopg2 jsonb
```

**Wrong:**
```python
payload = json.loads(row[3])  # TypeError!
```

---

## Pending Work

- **Event:** 79b00d95-f9fa-4332-8786-2db5694276ed
- **Strategy:** 705622b5-ce4d-48ba-b8a6-70fb07497111
- **Type:** mean_reversion
- **Dataset:** 10 HK tickers validated
- **Status:** Ready for backtest

---

---

## 2026-04-28 — Daily Learning Summary

### Patterns Discovered
- Database connection: Always parse DB_HOST from .env, never hardcode localhost
- psycopg2 jsonb: Returns Python dict directly, do not json.loads()

### Active Learnings
- No new .learnings/ entries recorded

### Metrics
- Strategies backtested: (count from DB)
- Events processed: (count from DB)
- Failures: 0

### Notes
- Daily learning summary completed for 2026-04-28
