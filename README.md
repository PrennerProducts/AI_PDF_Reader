# PDF-Reader On-Prem

Stand: 2026-04-29

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
- Stand 2026-04-27: alle 6 Canary-Provider liefern `validation=auto_accept`.

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
- JSON/CSV Export.
- SQL Export fuer das interne App-Schema.
- VenDoc-Dry-Run-Mapping mit Header-/Positionspayload und primaerem Bild als Base64.
- VenDoc-Export-Journal in Postgres fuer Dry-Runs und geblockte Live-Exportversuche.

Noch nicht umgesetzt:

- Echter VenDoc-MSSQL-Writer.
- Auth/Rollen.
- Persistente Background Jobs.
- Feldkorrekturen in der UI.

## VenDoc-Ziel

Dragan hat in der MSSQL-Importdatenbank vorbereitet:

- Datenbank: `SRTemp`
- Tabellen:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`

Der SQL-Zugriff wird noch durch CIBEX eingerichtet. Bis dahin ist der VenDoc-Export als Dry-Run-Mapping verfuegbar; Live-Write bleibt gesperrt.

## Wichtige API-Endpunkte

- `GET /health`
- `GET /ui`
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
- `POST /vendoc/export/{document_id}?dry_run=true|false`
- `GET /vendoc/export-jobs/{document_id}`
- `GET /vendoc/export-jobs/{document_id}/latest`
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

Aktueller Stand 2026-04-29:

- `.venv/bin/python -m pytest tests -q`: `165 passed`.
- `./infra/api-canary.sh`: 6/6 Provider `auto_accept`.

## Dokumentation

- `docs/README.md`
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
