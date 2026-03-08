CREATE INDEX IF NOT EXISTS idx_documents_status_created_at ON documents (status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_document_number ON documents (document_number);
CREATE INDEX IF NOT EXISTS idx_amount_lines_document_id ON document_amount_lines (document_id);
CREATE INDEX IF NOT EXISTS idx_line_items_document_id ON line_items (document_id);
CREATE INDEX IF NOT EXISTS idx_document_images_document_id ON document_images (document_id);

