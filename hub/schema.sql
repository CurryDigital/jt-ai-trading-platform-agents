-- Event-Driven Agent Architecture Database Schema
-- Hub Event Router + Strategy Lineage Tracking
-- PostgreSQL Version

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- EVENTS TABLE
-- Stores all system events - the event log
-- ============================================
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type TEXT NOT NULL,
    strategy_id TEXT,
    payload_json JSONB NOT NULL,
    source_agent TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_strategy ON events(strategy_id);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_events_source ON events(source_agent);
CREATE INDEX IF NOT EXISTS idx_events_payload ON events USING GIN (payload_json);

-- ============================================
-- EVENT_PROCESSING TABLE
-- Tracks which agents have processed which events
-- Prevents duplicate execution
-- ============================================
CREATE TABLE IF NOT EXISTS event_processing (
    event_id UUID NOT NULL,
    agent_name TEXT NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (event_id, agent_name),
    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_processing_agent ON event_processing(agent_name);
CREATE INDEX IF NOT EXISTS idx_processing_time ON event_processing(processed_at);

-- ============================================
-- STRATEGY_LINEAGE TABLE
-- Tracks full experiment configuration for reproducibility
-- Written by Algo agent when backtest completes
-- ============================================
CREATE TABLE IF NOT EXISTS strategy_lineage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    backtest_engine_version TEXT NOT NULL,
    strategy_parameters JSONB NOT NULL,
    result_metrics JSONB NOT NULL,
    source_event_id UUID NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    FOREIGN KEY (source_event_id) REFERENCES events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_lineage_strategy ON strategy_lineage(strategy_id);
CREATE INDEX IF NOT EXISTS idx_lineage_dataset ON strategy_lineage(dataset_version);
CREATE INDEX IF NOT EXISTS idx_lineage_engine ON strategy_lineage(backtest_engine_version);
CREATE INDEX IF NOT EXISTS idx_lineage_created ON strategy_lineage(created_at);
CREATE INDEX IF NOT EXISTS idx_lineage_event ON strategy_lineage(source_event_id);
CREATE INDEX IF NOT EXISTS idx_lineage_params ON strategy_lineage USING GIN (strategy_parameters);
CREATE INDEX IF NOT EXISTS idx_lineage_metrics ON strategy_lineage USING GIN (result_metrics);

-- ============================================
-- ROUTING TABLE (Future Enhancement)
-- Could move routing rules to DB for dynamic config
-- For now, routing is static in Hub code
-- ============================================
CREATE TABLE IF NOT EXISTS routing_rules (
    event_type TEXT PRIMARY KEY,
    target_agent TEXT NOT NULL,
    enabled BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- ============================================
-- VIEWS
-- ============================================

-- Pending events for each agent
CREATE OR REPLACE VIEW pending_events AS
SELECT 
    e.id,
    e.event_type,
    e.strategy_id,
    e.source_agent,
    e.created_at
FROM events e
LEFT JOIN event_processing ep ON e.id = ep.event_id
WHERE ep.event_id IS NULL;

-- Event processing status
CREATE OR REPLACE VIEW event_status AS
SELECT 
    e.id,
    e.event_type,
    e.strategy_id,
    e.source_agent,
    COUNT(ep.agent_name) as processed_count,
    STRING_AGG(ep.agent_name, ', ') as processed_by,
    e.created_at
FROM events e
LEFT JOIN event_processing ep ON e.id = ep.event_id
GROUP BY e.id;

-- Strategy history with metrics
CREATE OR REPLACE VIEW strategy_history AS
SELECT 
    sl.strategy_id,
    sl.dataset_version,
    sl.backtest_engine_version,
    sl.strategy_parameters,
    sl.result_metrics,
    e.event_type as last_event,
    e.source_agent as last_agent,
    sl.created_at as completed_at
FROM strategy_lineage sl
JOIN events e ON sl.source_event_id = e.id
ORDER BY sl.created_at DESC;

-- Pending work by agent
CREATE OR REPLACE VIEW pending_work AS
SELECT 
    rr.target_agent,
    e.id as event_id,
    e.event_type,
    e.strategy_id,
    e.source_agent as emitted_by,
    e.created_at
FROM routing_rules rr
JOIN events e ON rr.event_type = e.event_type
LEFT JOIN event_processing ep ON e.id = ep.event_id AND ep.agent_name = rr.target_agent
WHERE rr.enabled = TRUE
  AND ep.event_id IS NULL;

-- ============================================
-- FUNCTIONS
-- ============================================

-- Function to record event processing
CREATE OR REPLACE FUNCTION record_processing(
    p_event_id UUID,
    p_agent_name TEXT
) RETURNS VOID AS $$
BEGIN
    INSERT INTO event_processing (event_id, agent_name)
    VALUES (p_event_id, p_agent_name)
    ON CONFLICT (event_id, agent_name) DO NOTHING;
END;
$$ LANGUAGE plpgsql;

-- Function to emit event
CREATE OR REPLACE FUNCTION emit_event(
    p_event_type TEXT,
    p_strategy_id TEXT,
    p_payload JSONB,
    p_source_agent TEXT
) RETURNS UUID AS $$
DECLARE
    v_event_id UUID;
BEGIN
    INSERT INTO events (event_type, strategy_id, payload_json, source_agent)
    VALUES (p_event_type, p_strategy_id, p_payload, p_source_agent)
    RETURNING id INTO v_event_id;
    
    RETURN v_event_id;
END;
$$ LANGUAGE plpgsql;

-- Function to record strategy lineage
CREATE OR REPLACE FUNCTION record_lineage(
    p_strategy_id TEXT,
    p_dataset_version TEXT,
    p_engine_version TEXT,
    p_parameters JSONB,
    p_metrics JSONB,
    p_source_event_id UUID
) RETURNS UUID AS $$
DECLARE
    v_lineage_id UUID;
BEGIN
    INSERT INTO strategy_lineage (
        strategy_id, 
        dataset_version, 
        backtest_engine_version, 
        strategy_parameters, 
        result_metrics, 
        source_event_id
    )
    VALUES (
        p_strategy_id, 
        p_dataset_version, 
        p_engine_version, 
        p_parameters, 
        p_metrics, 
        p_source_event_id
    )
    RETURNING id INTO v_lineage_id;
    
    RETURN v_lineage_id;
END;
$$ LANGUAGE plpgsql;

-- ============================================
-- INITIAL DATA
-- ============================================

-- Insert default routing rules
INSERT INTO routing_rules (event_type, target_agent) VALUES
    ('strategy.created', 'de'),
    ('dataset.ready', 'algo'),
    ('backtest.completed', 'qa'),
    ('qa.validated', 'platform'),
    ('platform.deployed', 'tradinghub')
ON CONFLICT (event_type) DO NOTHING;

-- Insert a system startup event
INSERT INTO events (event_type, strategy_id, payload_json, source_agent)
VALUES (
    'system.startup',
    NULL,
    '{"version": "1.0.0", "message": "Hub Event Router initialized"}',
    'hub'
);
