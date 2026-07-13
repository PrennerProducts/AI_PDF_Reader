# Deployment & Environment (infra/)

## Welche `.env` gilt?

**`infra/.env` ist die einzige maßgebliche Env-Datei.**

Docker Compose liest bei `-f infra/docker-compose.yml` die `.env` aus dem
Verzeichnis der Compose-Datei — also **`infra/.env`**, *nicht* die `.env` im
Repo-Root. Eine Root-`.env` wird von Docker ignoriert.

Damit nichts auseinanderläuft, ist die Root-`.env` ein Symlink auf `infra/.env`:

```bash
ls -la .env        # .env -> infra/.env
```

Falls der Symlink fehlt, so herstellen (im Repo-Root):

```bash
ln -sf infra/.env .env
```

> `.env`-Dateien sind in `.gitignore` und liegen **nur auf dem Server**, nicht im Repo.

## Deploy (Standard)

Nach `git pull` – Code ist als Volume gemountet, daher reicht ein Restart des
api-Containers; die DB-Migrationen laufen beim Start automatisch:

```bash
cd ~/AI_PDF_Reader
git pull
docker restart pdr-api
docker logs pdr-api --tail 20     # "Applied DB migrations: ..." + "Application startup complete"
```

## Wann Container NEU erstellen (statt nur Restart)

Ein `restart` liest **geänderte Umgebungsvariablen NICHT** neu. Wenn du in
`infra/.env` etwas geändert hast (z. B. `APP_AUTH_ENABLED`), muss der
api-Container neu erstellt werden — **ohne die Postgres anzufassen**:

```bash
docker compose -f infra/docker-compose.yml up -d --no-deps --force-recreate api
docker exec pdr-api printenv APP_AUTH_ENABLED   # Kontrolle
```

- `--no-deps` → die Datenbank (`pdr-postgres`) wird **nicht** berührt.
- **Kein `-p`** verwenden. Die laufenden Container gehören zum Default-Projekt;
  mit `-p ai-pdf-reader` gibt es einen Namenskonflikt (`pdr-postgres already in use`).

## ⚠️ Datenbank / Volume — NIEMALS

- **Nie** `docker rm pdr-postgres` + `docker compose up -d` in der Hoffnung, es
  „neu aufzusetzen". Das Daten-Volume heißt `pg_data` → pro Projekt
  `<projekt>_pg_data`. Ein `up -d` unter einem anderen Projektnamen erstellt ein
  **neues, leeres** Volume → die DB wirkt leer (Daten sind noch da, aber nicht
  gemountet). Das hat hier schon einmal zu scheinbarem Datenverlust geführt.
- DB-Änderungen laufen ausschließlich über Migrationen in `api/migrations/`
  (werden beim api-Start automatisch angewendet, verfolgt in `schema_migrations`).

## Aufgelöste Konfiguration prüfen

```bash
docker compose -f infra/docker-compose.yml config | grep -i <VARIABLE>
```

Zeigt den Wert, den Compose tatsächlich aus `infra/.env` auflöst.
