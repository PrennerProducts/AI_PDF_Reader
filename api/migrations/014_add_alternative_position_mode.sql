ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS alternative_position_mode TEXT NOT NULL DEFAULT 'nested';
