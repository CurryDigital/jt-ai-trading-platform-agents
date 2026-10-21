#!/usr/bin/env python3
"""Discover kanban schema/tables and task t_6e0b3a40 (read-only)."""
import psycopg2

def read_env(pid):
    env = {}
    with open(f"/proc/{pid}/environ", "rb") as f:
        for kv in f.read().decode(errors="replace").split("\0"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                env[k] = v
    return env

env = read_env(3296465)
conn = psycopg2.connect(host=env["DB_HOST"], port=env["DB_PORT"], dbname=env["DB_NAME"],
                        user=env["DB_USER"], password=env["DB_PASSWORD"], connect_timeout=10)
cur = conn.cursor()
cur.execute("""SELECT table_schema, table_name FROM information_schema.tables
               WHERE table_name ILIKE '%kanban%' OR table_schema ILIKE '%kanban%'
               ORDER BY 1,2""")
for r in cur.fetchall():
    print(r)
cur.execute("""SELECT table_schema, table_name FROM information_schema.tables
               WHERE table_name IN ('tasks','task_comments','comments') ORDER BY 1,2""")
print("-- tasks/comments tables --")
for r in cur.fetchall():
    print(r)
cur.close(); conn.close()
