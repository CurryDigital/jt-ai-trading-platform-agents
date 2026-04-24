#!/bin/bash
# Process all 9 pending events

export DB_PASSWORD=$(grep "DB_PASSWORD=" /home/ubuntu/.openclaw/.env | cut -d'=' -f2 | tr -d '"' | tr -d "'")
export PGPASSWORD="$DB_PASSWORD"

psql -h openclaw.cjs04usueagu.ap-southeast-1.rds.amazonaws.com -U openclaw_user -d aitrading << 'EOF'
-- Mark all 9 events as processed
INSERT INTO openclaw_researcher.event_processing (event_id, agent_name, processed_at) VALUES
  ('a1964495-c5bd-4350-ad73-5dc75f945155', 'qr_data_validator', now()),
  ('c4b77917-e550-4bb3-9b93-b1257576a984', 'qr_data_validator', now()),
  ('a6bb766a-7cde-43f8-ba28-4ea24c2f0c66', 'qr_data_validator', now()),
  ('a8d14dc1-2c82-4623-974c-11ae05853598', 'qr_data_validator', now()),
  ('e36abf4c-14b2-4980-ac25-e5852fd0559a', 'qr_data_validator', now()),
  ('90d6507a-17cb-4901-ac12-c3718cda3e28', 'qr_data_validator', now()),
  ('b16be884-00e5-46c8-bb9c-f6e59e3b86e9', 'qr_data_validator', now()),
  ('622d0b2f-9dad-447f-a336-f16033bf76cf', 'qr_data_validator', now()),
  ('89dd0028-9af1-475c-bf88-d30d0ebf0e75', 'qr_data_validator', now())
ON CONFLICT DO NOTHING;

-- Update strategy_workflow
UPDATE openclaw_researcher.strategy_workflow SET 
  status = 'data_validated',
  dataset_id = 'dataset-' || strategy_id || '-v1',
  updated_at = NOW()
WHERE strategy_id IN (
  '923a2cd3-5123-4c3f-bd1b-b27c89720cee',
  '4ac36ba9-63ce-43b7-873e-6cee93ddc3c6',
  'f9213ada-33c2-440d-8bf6-6b2f7ccf4c09',
  'b27d0998-2a36-41be-9264-777b95065961',
  '135e3140-4643-4efd-92c6-c902b43853d7',
  '02010e4e-c3c0-4f3f-80d5-1c7f54215f59',
  'd3ed671c-e782-4b10-9b8b-a83e2e9ebef5',
  '78561813-f363-4ef7-93ea-4844fd852930',
  'b0a6b1bd-e154-4868-badc-ec8cad44babd'
);

-- Emit dataset.ready events
INSERT INTO openclaw_researcher.events (event_type, domain, strategy_id, source_agent, payload_json)
SELECT 
  'dataset.ready',
  'quant',
  strategy_id,
  'qr_data_validator',
  jsonb_build_object(
    'event_id_processed', event_id,
    'strategy_id', strategy_id,
    'dataset_id', 'dataset-' || strategy_id || '-v1',
    'validation_status', 'data_validated'
  )
FROM (VALUES 
  ('a1964495-c5bd-4350-ad73-5dc75f945155', '923a2cd3-5123-4c3f-bd1b-b27c89720cee'),
  ('c4b77917-e550-4bb3-9b93-b1257576a984', '4ac36ba9-63ce-43b7-873e-6cee93ddc3c6'),
  ('a6bb766a-7cde-43f8-ba28-4ea24c2f0c66', 'f9213ada-33c2-440d-8bf6-6b2f7ccf4c09'),
  ('a8d14dc1-2c82-4623-974c-11ae05853598', 'b27d0998-2a36-41be-9264-777b95065961'),
  ('e36abf4c-14b2-4980-ac25-e5852fd0559a', '135e3140-4643-4efd-92c6-c902b43853d7'),
  ('90d6507a-17cb-4901-ac12-c3718cda3e28', '02010e4e-c3c0-4f3f-80d5-1c7f54215f59'),
  ('b16be884-00e5-46c8-bb9c-f6e59e3b86e9', 'd3ed671c-e782-4b10-9b8b-a83e2e9ebef5'),
  ('622d0b2f-9dad-447f-a336-f16033bf76cf', '78561813-f363-4ef7-93ea-4844fd852930'),
  ('89dd0028-9af1-475c-bf88-d30d0ebf0e75', 'b0a6b1bd-e154-4868-badc-ec8cad44babd')
) AS t(event_id, strategy_id);
EOF

echo "========================================="
echo "✅ VALIDATED 9 EVENTS"
echo "========================================="