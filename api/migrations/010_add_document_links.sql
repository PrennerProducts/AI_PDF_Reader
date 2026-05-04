ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS linked_offer_document_id BIGINT REFERENCES documents(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_documents_linked_offer_document_id
    ON documents (linked_offer_document_id);

CREATE INDEX IF NOT EXISTS idx_documents_offer_lookup
    ON documents (supplier_name, document_type, document_number);
