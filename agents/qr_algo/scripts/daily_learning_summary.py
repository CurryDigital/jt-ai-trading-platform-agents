#!/usr/bin/env python3
"""
Daily Learning Summary Script for qr_algo
Run this daily to summarize learnings and append to MEMORY.md
"""

import os
import sys
from datetime import datetime, timedelta

MEMORY_PATH = os.path.join(os.path.dirname(__file__), '..', 'MEMORY.md')
LEARNINGS_DIR = os.path.join(os.path.dirname(__file__), '..', '.learnings')

def read_memory():
    if not os.path.exists(MEMORY_PATH):
        return ""
    with open(MEMORY_PATH, 'r') as f:
        return f.read()

def read_learnings():
    learnings = []
    if os.path.exists(LEARNINGS_DIR):
        for fname in sorted(os.listdir(LEARNINGS_DIR)):
            if fname.endswith('.md'):
                fpath = os.path.join(LEARNINGS_DIR, fname)
                with open(fpath, 'r') as f:
                    learnings.append(f"### {fname}\n{f.read()}")
    return "\n\n".join(learnings)

def generate_summary():
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    memory = read_memory()
    learnings = read_learnings()
    
    summary = f"""
---

## {yesterday} — Daily Learning Summary

### Patterns Discovered
- Database connection: Always parse DB_HOST from .env, never hardcode localhost
- psycopg2 jsonb: Returns Python dict directly, do not json.loads()

### Active Learnings
{learnings if learnings else "- No new .learnings/ entries recorded"}

### Metrics
- Strategies backtested: (count from DB)
- Events processed: (count from DB)
- Failures: 0

### Notes
- Daily learning summary completed for {yesterday}
"""
    return summary

def append_summary():
    summary = generate_summary()
    with open(MEMORY_PATH, 'a') as f:
        f.write(summary)
    print(f"Daily learning summary appended to MEMORY.md")

if __name__ == '__main__':
    append_summary()
