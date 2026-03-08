CREATE TABLE IF NOT EXISTS document_amount_lines (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    line_type TEXT NOT NULL,
    label_raw TEXT NOT NULL,
    percent NUMERIC(8, 4),
    base_amount NUMERIC(14, 2),
    amount NUMERIC(14, 2) NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0
);

