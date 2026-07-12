-- Benutzerverwaltung: Admin-Rolle + Passwort-aendern-Pflicht (erster Login).
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE app_users ADD COLUMN IF NOT EXISTS must_change_password BOOLEAN NOT NULL DEFAULT FALSE;

-- Den aeltesten Benutzer zum Admin machen, falls noch kein Admin existiert
-- (damit die bestehende Installation nicht ohne Administrator dasteht).
UPDATE app_users
SET is_admin = TRUE
WHERE id = (SELECT id FROM app_users ORDER BY created_at ASC, id ASC LIMIT 1)
  AND NOT EXISTS (SELECT 1 FROM app_users WHERE is_admin = TRUE);
