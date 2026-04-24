# TOOLS.md - Local Notes

## Database
- **Host:** `openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com`
- **Port:** 5432
- **DB:** `aitrading`
- **User:** `openclaw_user`
- **Auth:** IAM via EC2 instance profile
- **Region:** `ap-southeast-1`

## Python Env
- Shared scripts: `shared/scripts/db.py`
- Path setup: `sys.path.insert(0, 'shared/scripts')`

## Workspace
- Base: `/home/ubuntu/.openclaw/workspace/de/`
- Logs: `/home/ubuntu/.openclaw/workspace/de/logs/`
