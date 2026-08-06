-- ============================================================================
-- ARTIFACT 20: Ledger Archive (monthly compression companion to canonical_event_log)
-- ============================================================================
--
-- WHY THIS TABLE EXISTS, NOT AN UPDATE/DELETE ON canonical_event_log:
--
-- canonical_event_log has trg_canonical_event_log_immutable, which raises on
-- ANY UPDATE or DELETE. That's intentional -- it's the mechanism that makes
-- the hash chain tamper-evident. A monthly job that compresses rows "in
-- place" would have to weaken or bypass that trigger, which defeats the
-- entire point of the ledger.
--
-- Instead: canonical_event_log stays exactly as-is, forever, untouched.
-- This table holds a gzip-compressed COPY of old rows' payloads, written
-- once per row, never updated or deleted (own immutability trigger below).
-- The original row's current_hash is stored alongside the compressed copy,
-- so at any point you can decompress and re-verify it matches the live
-- ledger row bit-for-bit -- the archive can never silently drift from the
-- source of truth.
--
-- This does not shrink canonical_event_log itself (Postgres already
-- TOAST-compresses large JSONB automatically, and the row must remain for
-- the hash chain to stay verifiable). What it gives you is a permanent,
-- much smaller, queryable copy -- useful for reporting, export, or eventual
-- migration to cheap cold storage -- without ever deleting or mutating the
-- original ledger.
-- ============================================================================

CREATE TABLE IF NOT EXISTS canonical_event_log_archive (
    archive_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_event_id UUID NOT NULL REFERENCES canonical_event_log(event_id),
    tenant_id VARCHAR(256) NOT NULL,
    ticket_id VARCHAR(256) NOT NULL,
    original_timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
    original_current_hash VARCHAR(64) NOT NULL,
    compressed_payload BYTEA NOT NULL,
    payload_sha256 VARCHAR(64) NOT NULL,
    archived_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archive_run_month DATE NOT NULL,
    UNIQUE (original_event_id)
);

CREATE INDEX idx_archive_by_tenant_ticket ON canonical_event_log_archive(tenant_id, ticket_id);
CREATE INDEX idx_archive_by_run_month ON canonical_event_log_archive(archive_run_month);

CREATE OR REPLACE FUNCTION reject_archive_mutation() RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'canonical_event_log_archive is append-only: % on archive_id % is not permitted',
        TG_OP, COALESCE(OLD.archive_id, NULL);
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_archive_immutable ON canonical_event_log_archive;
CREATE TRIGGER trg_archive_immutable
    BEFORE UPDATE OR DELETE ON canonical_event_log_archive
    FOR EACH ROW EXECUTE FUNCTION reject_archive_mutation();

-- Tracks each monthly run so the job is idempotent / re-runnable safely.
CREATE TABLE IF NOT EXISTS archive_run_log (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_month DATE NOT NULL UNIQUE,
    started_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP WITH TIME ZONE,
    rows_archived INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL DEFAULT 'running'
        CHECK (status IN ('running', 'completed', 'failed'))
);
