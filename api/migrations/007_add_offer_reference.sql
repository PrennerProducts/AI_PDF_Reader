ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS document_type TEXT NOT NULL DEFAULT 'angebot';

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS offer_reference TEXT;
