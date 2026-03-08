CREATE TABLE IF NOT EXISTS line_items (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    position_no TEXT,
    lv_pos TEXT,
    is_alternative BOOLEAN NOT NULL DEFAULT FALSE,
    quantity NUMERIC(14, 4),
    unit TEXT,
    width_mm NUMERIC(12, 2),
    height_mm NUMERIC(12, 2),
    description_short TEXT,
    description_long TEXT,
    unit_price NUMERIC(14, 2),
    line_total NUMERIC(14, 2),
    page_ref INTEGER,
    confidence NUMERIC(5, 4),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
);

