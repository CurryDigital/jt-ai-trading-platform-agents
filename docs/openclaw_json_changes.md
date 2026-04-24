# openclaw.json Changes for v6.1

## How to apply

Edit `~/.openclaw/openclaw.json` and make the following changes.

---

## 1. Add new agents to `agents.list[]`

Add these entries to the `agents.list` array:

```json
{
    "id": "qr_researcher",
    "name": "qr_researcher",
    "workspace": "/home/ubuntu/.openclaw/workspace/quant_research/agents/qr_researcher",
    "agentDir": "/home/ubuntu/.openclaw/agents/qr_researcher/agent",
    "heartbeat": {
        "every": "360m",
        "lightContext": false
    }
},
{
    "id": "qr_macro_sentinel",
    "name": "qr_macro_sentinel",
    "workspace": "/home/ubuntu/.openclaw/workspace/quant_research/agents/qr_macro_sentinel",
    "agentDir": "/home/ubuntu/.openclaw/agents/qr_macro_sentinel/agent",
    "heartbeat": {
        "every": "120m",
        "lightContext": true
    }
},
{
    "id": "qr_architect",
    "name": "qr_architect",
    "workspace": "/home/ubuntu/.openclaw/workspace/quant_research/agents/qr_architect",
    "agentDir": "/home/ubuntu/.openclaw/agents/qr_architect/agent",
    "heartbeat": {
        "every": "60m",
        "lightContext": true
    }
},
{
    "id": "qr_debate",
    "name": "qr_debate",
    "workspace": "/home/ubuntu/.openclaw/workspace/quant_research/agents/qr_debate",
    "agentDir": "/home/ubuntu/.openclaw/agents/qr_debate/agent"
}
```

## 2. Update Hub heartbeat to 5 minutes

Change the existing `qr_hub` entry:

```json
{
    "id": "qr_hub",
    "heartbeat": {
        "every": "5m",
        "target": "none",
        "prompt": "Run your routing procedure from AGENTS.md now.",
        "lightContext": false
    }
}
```

## 3. ALL pipeline agents get self-polling heartbeats

sessions_send is unreliable on OpenClaw (known timeout issues, agents
not waking). Pipeline agents MUST self-poll for their own work.
Hub sessions_send is optional acceleration only.

Pipeline agents poll every 3 minutes with lightContext: true to save tokens:

```json
{ "id": "qr_data_validator", "heartbeat": { "every": "3m", "lightContext": true } },
{ "id": "qr_algo",           "heartbeat": { "every": "3m", "lightContext": true } },
{ "id": "qr_risk",           "heartbeat": { "every": "3m", "lightContext": true } },
{ "id": "qr_debate",         "heartbeat": { "every": "3m", "lightContext": true } },
{ "id": "qr_qa",             "heartbeat": { "every": "3m", "lightContext": true } },
{ "id": "qr_idea_intake",    "heartbeat": { "every": "5m", "lightContext": true } }
```

Other always-on agents keep existing heartbeats:
- qr_monitor: "30m"
- qr_etl_manager: "60m" (daily refresh)
- qr_exp_manager: "60m" (nightly cycle)

## 4. Update agentToAgent allow list

Add new agents to the allow list:

```json
{
    "tools": {
        "agentToAgent": {
            "enabled": true,
            "allow": [
                "qr_hub",
                "qr_monitor",
                "qr_idea_intake",
                "qr_etl_manager",
                "qr_exp_manager",
                "qr_data_validator",
                "qr_algo",
                "qr_risk",
                "qr_qa",
                "qr_debate",
                "qr_researcher",
                "qr_macro_sentinel",
                "qr_architect"
            ]
        }
    }
}
```

## 5. Set maxPingPongTurns to 0

Add to session config to prevent reply-back loops:

```json
{
    "session": {
        "dmScope": "per-channel-peer",
        "agentToAgent": {
            "maxPingPongTurns": 0
        }
    }
}
```

## 6. Create agent directories for new agents

```bash
mkdir -p ~/.openclaw/agents/qr_researcher/agent
mkdir -p ~/.openclaw/agents/qr_macro_sentinel/agent
mkdir -p ~/.openclaw/agents/qr_architect/agent
mkdir -p ~/.openclaw/agents/qr_debate/agent
```
