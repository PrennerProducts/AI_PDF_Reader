-- Merkt sich, ob die AB->Angebot-Zuordnung manuell (per Dropdown) gesetzt wurde.
-- Manuell gesetzte Zuordnungen duerfen vom automatischen Textabgleich
-- (refresh_document_links) NICHT ueberschrieben werden, weil dieselbe
-- Angebotsnummer bei einem Lieferanten mehrfach vorkommen kann.
ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS offer_link_manual BOOLEAN NOT NULL DEFAULT FALSE;
