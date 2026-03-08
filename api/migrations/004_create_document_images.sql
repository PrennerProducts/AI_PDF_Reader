CREATE TABLE IF NOT EXISTS document_images (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    page_ref INTEGER NOT NULL,
    image_index INTEGER NOT NULL,
    mime_type TEXT,
    storage_path TEXT NOT NULL,
    sha256 TEXT,
    width INTEGER,
    height INTEGER,
    bytes_size BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, page_ref, image_index)
);

