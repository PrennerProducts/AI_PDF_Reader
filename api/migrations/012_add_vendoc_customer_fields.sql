ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS vendoc_customer_oid TEXT,
    ADD COLUMN IF NOT EXISTS vendoc_customer_number TEXT,
    ADD COLUMN IF NOT EXISTS vendoc_customer_uid_number TEXT,
    ADD COLUMN IF NOT EXISTS vendoc_customer_inactive BOOLEAN;
