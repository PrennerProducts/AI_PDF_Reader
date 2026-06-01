# PDF-Reader On-Prem

Stand: 2026-05-28

On-Prem-App fuer Angebots-PDFs: Upload, Parser, Bildextraktion, Validierung, Review/Freigabe und Export. Ziel fuer den Produktivbetrieb ist ein direkter VenDoc-Import in eine externe MSSQL-Datenbank `SRTemp`.

## Quickstart

Aus dem Repo-Root:

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up -d --build
```

Alternativ direkt aus `infra/`:

```bash
cd infra
cp .env.example .env
docker compose up -d --build
```

Pruefen:

```bash
curl http://localhost:8000/health
./infra/api-canary.sh
```

UI:

```text
http://localhost:8000/ui
```

Auth fuer Serverbetrieb:

```dotenv
APP_AUTH_ENABLED=true
APP_BOOTSTRAP_USERNAME=admin
APP_BOOTSTRAP_PASSWORD=<sicheres-passwort>
APP_BOOTSTRAP_DISPLAY_NAME=Admin
```

Bei aktivierter Auth meldet sich der Canary mit `PDR_CANARY_USERNAME` /
`PDR_CANARY_PASSWORD` an. Falls diese Variablen fehlen, nutzt er
`APP_BOOTSTRAP_USERNAME` / `APP_BOOTSTRAP_PASSWORD` aus `.env`.

## Lokale `.env` fuer VPN / MSSQL

Wenn du lokal mit VPN arbeitest und den VenDoc-Live-Write gegen `SRTemp` testen willst,
nutze im Repo-Root eine `.env`, weil `docker compose -f infra/docker-compose.yml ...`
die Variablen von dort liest.

Start:

```bash
cp .env.example .env
```

Dann die MSSQL-Werte setzen:

```dotenv
VENDOC_MSSQL_ENABLED=true
VENDOC_MSSQL_HOST=...
VENDOC_MSSQL_PORT=57676
VENDOC_MSSQL_DATABASE=SRTemp
VENDOC_MSSQL_USER=VenDoc
VENDOC_MSSQL_PASSWORD=...
VENDOC_MSSQL_ENCRYPT=true
VENDOC_MSSQL_TRUST_SERVER_CERTIFICATE=true
VENDOC_MSSQL_TIMEOUT_SECONDS=30
VENDOC_MSSQL_DRIVER=ODBC Driver 18 for SQL Server
```

Danach:

```bash
docker compose -f infra/docker-compose.yml up -d --build api
curl -sS http://localhost:8000/vendoc/health
```

## CPU-only Server

Fuer Ubuntu-Server ohne NVIDIA-GPU:

```bash
cd infra
cp .env.cpu.example .env
docker compose -f docker-compose.cpu.yml up -d --build
```

Der Produktivmodus ist rein lokal und parserbasiert. Es werden keine Cloud-Dienste,
keine externen APIs und keine KI-/Modellkomponenten fuer die Verarbeitung verwendet.

## Live Mode

```bash
./infra/dev-watch.sh
```

Startet/recreated den Stack, prueft Healthchecks und streamt Container-Logs.

## API Canary

```bash
./infra/api-canary.sh
```

Verarbeitet einen festen Provider-Satz gegen die laufende API und prueft Lieferant, Belegnummer, Datum, Positionenzahl und Validierungsstatus.

Aktueller Hinweis:

- Die API laeuft.
- Der Canary verarbeitet alle Dokumente.
- Stand 2026-05-28: alle 8 Canary-Faelle liefern `validation=auto_accept`.
- Der Canary kann sich bei aktivierter App-Auth automatisch anmelden.

## Aktueller Funktionsumfang

- PDF Upload.
- Parser fuer mehrere Angebotsanbieter.
- Auftragsbestaetigungen als Non-Offer-Korpus.
- PDF-Text- und Bildextraktion.
- Heuristische Bildzuordnung.
- Parser-only-Verarbeitung ohne KI-/Cloud-Abhaengigkeiten.
- Angebot-zu-Auftragsbestaetigung-Verknuepfung ueber erkannte Angebotsreferenzen.
- Validierung von Pflichtfeldern, Summen, Positionen und Bildern.
- UI-Workbench mit Review, Freigabe und manueller Bildzuordnung.
- Login, Logout, Bootstrap-Benutzer und Audit-Log.
- JSON/CSV Export.
- SQL Export fuer das interne App-Schema.
- VenDoc-Dry-Run-Mapping mit Header-/Positionspayload und RTF-Bilddaten.
- VenDoc-MSSQL-Live-Writer fuer `SRTemp`, per ENV schaltbar.
- VenDoc-Export-Journal in Postgres fuer Dry-Runs, Live-Exports und Fehler.
- Kundenauswahl fuer `SRTemp` und `customer_id` im VenDoc-Header.
- Alternative Positionen mit Exportmodus `nested` oder `append`.

Noch nicht umgesetzt:

- Rollen und Berechtigungen.
- Persistente Background Jobs.
- Feldkorrekturen in der UI.
- Produktiver SRTemp-Live-Write ist noch vor Ort gegen die Zieltabellen zu verifizieren.

## VenDoc-Ziel

Dragan hat in der MSSQL-Importdatenbank vorbereitet:

- Datenbank: `SRTemp`
- Tabellen:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`

Der SQL-Zugriff laeuft ueber CIBEX/VPN. Der Writer ist im Code vorhanden und wird
mit `VENDOC_MSSQL_ENABLED=true` aktiviert. Dry-Run und SQL-Vorschau bleiben ohne
echten Write nutzbar; ein produktiver Live-Write muss vor Ort gegen `SRTemp`
fachlich kontrolliert werden.

## Wichtige API-Endpunkte

- `GET /health`
- `GET /ui`
- `GET /auth/me`
- `POST /auth/login`
- `POST /auth/logout`
- `POST /auth/users`
- `POST /upload`
- `GET /documents?limit=20`
- `POST /process/{document_id}?process_mode=parser_only`
- `GET /progress/{document_id}`
- `GET /result/{document_id}`
- `GET /relations/{document_id}`
- `POST /documents/{document_id}/line-items/{line_item_id}/assign-image`
- `DELETE /documents/{document_id}/line-items/{line_item_id}/assign-image`
- `POST /documents/{document_id}/line-items/{line_item_id}/review-check`
- `DELETE /documents/{document_id}/line-items/{line_item_id}/review-check`
- `POST /documents/{document_id}/approval`
- `DELETE /documents/{document_id}/approval`
- `GET /preview/{document_id}?format=json|csv`
- `GET /export/{document_id}?format=json|csv|sql&include_images_base64=true|false`
- `POST /match-images/{document_id}?strategy=heuristic`
- `GET /vendoc/customers`
- `PUT /documents/{document_id}/vendoc-customer`
- `PUT /documents/{document_id}/alternative-position-mode`
- `POST /vendoc/export/{document_id}?dry_run=true|false`
- `GET /vendoc/export-jobs/{document_id}`
- `GET /vendoc/export-jobs/{document_id}/latest`
- `GET /vendoc/import-state/{document_id}`
- `GET /vendoc/health`
- `POST /dev/parse-text`

## Neue Provider oder neue PDFs

Provider-Scaffold:

```bash
./infra/new-provider.sh muster_anbieter "Muster Anbieter GmbH"
```

Neue Angebots-PDFs zuerst nach:

```text
samples/pdfs/candidates/offers/<anbieter>/
```

Danach Tests und Provider-Matrix aktualisieren.

## Tests

Wichtige Checks:

```bash
python -m pytest tests/test_template_regression.py -q
python -m pytest tests/test_offer_corpus_smoke.py -q
python -m pytest tests/test_non_offer_corpus_smoke.py -q
python -m pytest tests/test_validation_provider_rules.py -q
python -m pytest tests/test_exporter_approval.py -q
./infra/api-canary.sh
```

Aktueller Stand 2026-05-28:

- `env PYTHONPATH=api .venv/bin/python -m pytest tests -q`: `209 passed, 2 warnings`.
- `./infra/api-canary.sh`: 8/8 Canary-Faelle `auto_accept`.

## Dokumentation

- `docs/README.md`
- `docs/RECENT_CHANGES.md`
- `docs/PLAN.md`
- `docs/STATUS.md`
- `docs/PRODUCTION_READINESS.md`
- `docs/TASKS.md`
- `docs/HOW_IT_WORKS.md`
- `docs/API.md`
- `docs/VENDOC_MSSQL_ACCESS_NOTES.md`
- `docs/PROVIDER_ONBOARDING.md`

## Datenverzeichnisse

- `data/uploads`
- `data/exports`
- `data/logs`
