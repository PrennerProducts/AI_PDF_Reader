ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS approval_status TEXT NOT NULL DEFAULT 'pending';

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS reviewed_by TEXT;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS approval_note TEXT;
