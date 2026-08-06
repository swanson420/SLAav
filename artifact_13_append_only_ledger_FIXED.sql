-- ============================================================================
-- ARTIFACT 13: Append-Only Ledger (FINAL — as deployed)
-- ============================================================================

CREATE TABLE IF NOT EXISTS canonical_event_log (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(256) NOT NULL,
    ticket_id VARCHAR(256) NOT NULL,
    event_type VARCHAR(64) NOT NULL CHECK (event_type IN ('New', 'Open', 'Pending', 'Solved', 'Closed')),
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    event_payload JSONB NOT NULL,
    write_origin VARCHAR(128) NOT NULL,
    decision_trace_id UUID,
    event_version INT NOT NULL,
    previous_hash VARCHAR(64),
    current_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_canonical_event_log_hash_chain
ON canonical_event_log(tenant_id, ticket_id, event_version, current_hash);

CREATE OR REPLACE FUNCTION reject_ledger_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'canonical_event_log is append-only: % on event_id % is not permitted',
        TG_OP, COALESCE(OLD.event_id, NULL);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_canonical_event_log_immutable ON canonical_event_log;
CREATE TRIGGER trg_canonical_event_log_immutable
    BEFORE UPDATE OR DELETE ON canonical_event_log
    FOR EACH ROW EXECUTE FUNCTION reject_ledger_mutation();

CREATE TABLE IF NOT EXISTS sla_root_cause_attribution (
    attribution_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id VARCHAR(256) NOT NULL UNIQUE,
    tenant_id VARCHAR(256) NOT NULL,
    failure_category VARCHAR(128) NOT NULL CHECK (failure_category IN (
        'Routing_Ping_Pong_Failure',
        'Pending_State_Abuse',
        'Triage_Delay',
        'Agent_Timeout',
        'System_Unavailable'
    )),
    impact_duration_minutes INT NOT NULL CHECK (impact_duration_minutes >= 0),
    financial_loss_share_usd DECIMAL(12, 2) NOT NULL CHECK (financial_loss_share_usd >= 0),
    attribution_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    computed_by_artifact VARCHAR(32) DEFAULT 'Artifact_15',
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_financial_attribution CHECK (financial_loss_share_usd <= 100000)
);

CREATE INDEX idx_sla_root_cause_by_ticket ON sla_root_cause_attribution(ticket_id);
CREATE INDEX idx_sla_root_cause_by_category ON sla_root_cause_attribution(tenant_id, failure_category);
CREATE INDEX idx_sla_root_cause_by_timestamp ON sla_root_cause_attribution(attribution_timestamp DESC);

CREATE TABLE IF NOT EXISTS event_lineage_chain (
    lineage_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id VARCHAR(256) NOT NULL,
    tenant_id VARCHAR(256) NOT NULL,
    event_sequence_index INT NOT NULL,
    event_version INT NOT NULL,
    current_hash VARCHAR(64) NOT NULL,
    previous_hash VARCHAR(64),
    causal_parent_event_id UUID REFERENCES canonical_event_log(event_id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_event_lineage_by_ticket ON event_lineage_chain(tenant_id, ticket_id, event_sequence_index);

CREATE TABLE IF NOT EXISTS consistency_quarantine (
    quarantine_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id VARCHAR(256) NOT NULL,
    tenant_id VARCHAR(256) NOT NULL,
    conflicting_event_id UUID REFERENCES canonical_event_log(event_id),
    conflict_type VARCHAR(128) NOT NULL,
    quarantine_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_quarantine_by_ticket ON consistency_quarantine(tenant_id, ticket_id);

CREATE TABLE IF NOT EXISTS cfo_financial_leakage_cache (
    ticket_id VARCHAR(256) NOT NULL,
    tenant_id VARCHAR(256) NOT NULL,
    cryptographic_proof_signature VARCHAR(64) NOT NULL,
    active_duration_minutes NUMERIC NOT NULL,
    financial_loss_share_usd DECIMAL(12, 2),
    elapsed_breach_minutes INT,
    view_snapshot_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticket_id, tenant_id)
);

CREATE INDEX idx_cfo_cache_by_tenant ON cfo_financial_leakage_cache(tenant_id);

CREATE TABLE IF NOT EXISTS coo_root_cause_attribution_cache (
    ticket_id VARCHAR(256) NOT NULL,
    tenant_id VARCHAR(256) NOT NULL,
    failure_category VARCHAR(128) NOT NULL,
    impact_duration_minutes INT,
    financial_loss_share_usd DECIMAL(12, 2),
    attribution_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    view_snapshot_timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (ticket_id, tenant_id)
);

CREATE INDEX idx_coo_cache_by_category ON coo_root_cause_attribution_cache(tenant_id, failure_category);

-- Added during Part 3 (external timestamp anchoring)
CREATE TABLE IF NOT EXISTS chain_anchors (
    anchor_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id VARCHAR(256) NOT NULL,
    anchored_hash VARCHAR(64) NOT NULL,
    ots_proof_bytes BYTEA NOT NULL,
    calendar_url VARCHAR(256) NOT NULL,
    submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TIMESTAMP WITH TIME ZONE
);

-- Migration placeholder
INSERT INTO sla_root_cause_attribution
    (ticket_id, tenant_id, failure_category, impact_duration_minutes, financial_loss_share_usd)
SELECT
    ticket_id, tenant_id,
    COALESCE((payload->>'root_cause'), 'Unknown') AS failure_category,
    COALESCE((payload->>'impact_minutes')::INT, 0) AS impact_duration_minutes,
    COALESCE((payload->>'financial_loss')::DECIMAL, 0.00) AS financial_loss_share_usd
FROM (
    SELECT 'placeholder_ticket_id'::VARCHAR AS ticket_id,
           'default_tenant'::VARCHAR AS tenant_id,
           '{}'::JSONB AS payload
    LIMIT 0
) historical_data
ON CONFLICT DO NOTHING;
