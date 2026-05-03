# Learning: Frontend Deployment Failure
**Date:** 2026-05-03
**Context:** User reported that frontend changes were not reflecting after `npm run build`.
**Root Cause:** The `npm run build` only updates the workspace `dist/` folder, but Nginx serves from `/var/www/trade.jtcml.com/`.
**Solution:**
1. Created a dedicated OpenClaw skill: `deploy-frontend`.
2. Bundled a deployment script: `scripts/deploy.sh` to handle build, sync, permissions, and nginx reload.
3. Registered the skill in `~/.openclaw/skills/`.
**Future Action:** Use `deploy-frontend` skill (or its script) for all future UI updates.
