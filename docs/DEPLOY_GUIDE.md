# Deployment Guide — v6.1

## Pre-deployment checklist

- [ ] Backup current workspace: `cp -r ~/.openclaw/workspace/quant_research ~/quant_research_backup_$(date +%Y%m%d)`
- [ ] Read docs/openclaw_json_changes.md
- [ ] Read docs/migration_006_v6.1.sql

## Step 1: Run database migration

```bash
psql -h $DB_HOST -U $DB_USER -d $DB_NAME -f docs/migration_006_v6.1.sql
```

This adds:
- conviction_score, debate_summary, frequency, strategy_description columns to strategy_workflow
- macro_events table
- debate.completed routing rule
- risk.evaluated routed to qr_debate instead of qr_qa
- Frequency-aware risk_config thresholds
- v_debate_work view

## Step 2: Deploy workspace files

Copy the v6.1 workspace files into your OpenClaw workspace.
**WARNING:** This replaces all AGENTS.md, SOUL.md, HEARTBEAT.md files.

```bash
WS=~/.openclaw/workspace/quant_research

# Root workspace files
cp AGENTS.md SOUL.md IDENTITY.md USER.md MEMORY.md TOOLS.md $WS/

# Skills (new + updated)
cp skills/*.md $WS/skills/

# .learnings templates
mkdir -p $WS/.learnings
cp .learnings/*.md $WS/.learnings/

# Agent workspace files (for each agent)
for agent in qr_hub qr_data_validator qr_algo qr_risk qr_debate qr_qa \
             qr_exp_manager qr_idea_intake qr_monitor qr_etl_manager \
             qr_researcher qr_macro_sentinel qr_architect; do
  mkdir -p $WS/agents/$agent
  cp agents/$agent/*.md $WS/agents/$agent/
done

# Docs
mkdir -p $WS/docs
cp docs/*.md $WS/docs/
cp docs/*.sql $WS/docs/
```

## Step 3: Delete SESSION.md files (not valid in OpenClaw)

```bash
find ~/.openclaw/workspace/quant_research -name "SESSION.md" -delete
echo "Deleted all SESSION.md files"
```

## Step 4: Delete old Python routing code

The Hub is now LLM-native. These files are no longer needed:

```bash
# Remove but keep as reference
mkdir -p $WS/docs/legacy
mv $WS/hub/hub_agent.py $WS/docs/legacy/ 2>/dev/null
mv $WS/hub/router.py $WS/docs/legacy/ 2>/dev/null
mv $WS/hub/sdk.py $WS/docs/legacy/ 2>/dev/null
mv $WS/hub/service.py $WS/docs/legacy/ 2>/dev/null
```

## Step 5: Create agent directories for new agents

```bash
mkdir -p ~/.openclaw/agents/qr_researcher/agent
mkdir -p ~/.openclaw/agents/qr_macro_sentinel/agent
mkdir -p ~/.openclaw/agents/qr_architect/agent
mkdir -p ~/.openclaw/agents/qr_debate/agent
```

## Step 6: Update openclaw.json

Follow docs/openclaw_json_changes.md to:
- Add 4 new agents (researcher, macro_sentinel, architect, debate)
- Update Hub heartbeat to 5m
- Update agentToAgent allow list with new agents
- Set maxPingPongTurns to 0

Then restart:
```bash
openclaw restart
```

## Step 7: Install ClawHub skills

```bash
# Self-improvement loop
openclaw skills install self-improving-agent

# Browser automation for researcher
npm install -g agent-browser
openclaw skills install agent-browser
```

## Step 8: Git init the workspace

```bash
cd ~/.openclaw/workspace/quant_research
git init
echo ".env" >> .gitignore
echo "*.pyc" >> .gitignore
echo "__pycache__/" >> .gitignore
echo ".openclaw/" >> .gitignore
git add .
git commit -m "v6.1 initial workspace state"
```

## Step 9: Verify

```bash
# Check agents are registered
openclaw agents list

# Check routing rules
psql -c "SELECT event_type, domain, target_agent FROM openclaw_researcher.routing_rules WHERE enabled ORDER BY domain, event_type"

# Test Hub heartbeat manually
openclaw agent -m 'Run your HEARTBEAT.md now' --agent qr_hub

# Submit a test idea
openclaw agent -m 'momentum on AAPL MSFT 20 day lookback last 3 years' --agent qr_idea_intake

# Watch events flow
watch -n 10 'psql -c "SELECT event_type, source_agent, strategy_id, created_at FROM openclaw_researcher.events ORDER BY created_at DESC LIMIT 10"'
```

## Step 10: Enable 24/7 operation

Once verified, the system runs autonomously:
- Hub routes events every 5 minutes
- Researcher generates ideas every 6 hours
- Macro Sentinel monitors events every 2 hours
- Architect improves the system every hour
- Monitor watches for stuck pipelines every 30 minutes
- ETL refreshes data daily
- Exp Manager runs nightly autonomous cycle

## Rollback

If anything breaks:
```bash
cp -r ~/quant_research_backup_YYYYMMDD ~/.openclaw/workspace/quant_research
openclaw restart
```
