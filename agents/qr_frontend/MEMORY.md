# MEMORY.md — qr_frontend

## Repo
URL: https://github.com/CurryDigital/jt-ai-trading-platform
Path: ~/web_app/

## Stack
- React 18 + Vite + Tailwind CSS v3
- FastAPI + uvicorn, Python 3.12
- All routes in: backend/app/main.py
- Main app: frontend/src/App.jsx

## Work log

### 2025-04-11 — Agent Initialization
What: Cloned repo, installed frontend (npm ci) and backend (pip3) dependencies, verified both builds work
Files: N/A (bootstrap)
Commit: 60dbb7b (initial)

### 2026-05-03 — Skill: `deploy-frontend` Created
**Principle:** I created a dedicated agent skill `deploy-frontend` to handle the build-and-sync process to the Nginx root.
**Action:** Created `~/.openclaw/skills/deploy-frontend` with `SKILL.md` and `scripts/deploy.sh`. Registered it as an OpenClaw-managed skill.
**Why:** This institutionalizes the "Lesson: Sync Frontend Build to Nginx Root" and makes it a reusable capability for any agent in this workspace.

### 2026-05-03 — Lesson: Sync Frontend Build to Nginx Root
**Principle:** Running `npm run build` only updates the `dist/` folder in the repository. For changes to reflect on the live site, they MUST be copied to the production web root (e.g., `/var/www/trade.jtcml.com`).
**Action:** After every frontend build, run `sudo cp -r ~/web_app/frontend/dist/* /var/www/trade.jtcml.com/` and ensure permissions are correct (`chown -R www-data`).
**Why:** The Nginx configuration for `trade.jtcml.com` serves static files from the system-level web root, not the user's workspace. Failure to copy results in the user seeing a stale version of the app despite a successful build.

### 2026-04-23 — Lesson: Escalate backend data issues to qr_etl_manager
**Principle:** When the frontend shows empty data because a consumption view is empty, missing, or has stale data, do NOT add fallback hacks in FastAPI routes.  
**Action:** Immediately notify `qr_etl_manager` (Telegram group or heartbeat session) with the specific view/table name and what's needed.  
**Why:** The DE/ETL agent owns data ingestion. The frontend agent owns UI + API routes. Crossing that boundary creates tech debt.

### 2026-04-21 — Lesson: No DB fallback hacks in API routes
**Principle:** FastAPI routes must read only from the curated SQL layer (consumption/gold views).  
**Never add fallback logic** that directly queries raw IBKR tables or bypasses the ETL pipeline when the curated view is empty.  
**Why:** This violates clean architecture — Frontend → FastAPI → SQL. Data ingestion is the ETL manager's job, not the API layer's.  
**Context:** Portfolio tab showed $0/0 positions because `consumption.Portfolio_Positions_Current` was empty (no ETL sync running). Temptation was to add fallback to `gold.ibkr_positions_live` directly in the route. Reverted immediately.  
**Correct fix:** The ETL/DE agent must sync IBKR positions into the consumption layer. FastAPI stays dumb and reads only what it's given.
