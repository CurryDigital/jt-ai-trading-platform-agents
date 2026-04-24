# TOOLS.md — Infrastructure

## RDS PostgreSQL
- Host: DB_HOST env var
- Schema: openclaw_researcher
- Auth: IAM token via boto3
- Gold layer: gold.stock_metrics_history (READ-ONLY VIEW)

## EC2
- Region: ap-southeast-1
- Workspace: /home/ubuntu/.openclaw/workspace/quant_research

## OpenClaw agent session keys
| Agent | Session key |
|-------|-------------|
| qr_hub | agent:qr_hub:main |
| qr_monitor | agent:qr_monitor:main |
| qr_researcher | agent:qr_researcher:main |
| qr_macro_sentinel | agent:qr_macro_sentinel:main |
| qr_architect | agent:qr_architect:main |
| qr_idea_intake | agent:qr_idea_intake:main |
| qr_etl_manager | agent:qr_etl_manager:main |
| qr_exp_manager | agent:qr_exp_manager:main |
| qr_data_validator | agent:qr_data_validator:main |
| qr_algo | agent:qr_algo:main |
| qr_risk | agent:qr_risk:main |
| qr_debate | agent:qr_debate:main |
| qr_qa | agent:qr_qa:main |
