CREATE TABLE IF NOT EXISTS vendoc_export_jobs (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    external_document_id UUID NOT NULL,
    dry_run BOOLEAN NOT NULL DEFAULT TRUE,
    status TEXT NOT NULL,
    target_server TEXT,
    target_database TEXT,
    line_item_count INTEGER NOT NULL DEFAULT 0,
    warning_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    error_text TEXT,
    approval_status TEXT,
    reviewed_by TEXT,
    reviewed_at TIMESTAMPTZ,
    payload_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendoc_export_jobs_document_id
    ON vendoc_export_jobs (document_id, id DESC);

CREATE INDEX IF NOT EXISTS idx_vendoc_export_jobs_external_document_id
    ON vendoc_export_jobs (external_document_id);
