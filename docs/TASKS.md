# Umsetzungstasks

Stand: 2026-04-27

Diese Liste ist der konkrete Backlog aus `docs/PLAN.md`.

## P0 - VenDoc und Release-Faehigkeit

### P0-001 VenDoc Dry-Run Mapper

Status: offen

Ziel:

- Aus einem `GET /result/{document_id}` Ergebnis einen VenDoc-kompatiblen Header-/Positionspayload bauen.

Tasks:

- `api/vendoc_exporter.py` erstellen.
- Header-Mapping implementieren.
- Positions-Mapping implementieren.
- Primaeres Bild als Base64 anbinden.
- Pflichtfelder validieren.
- Unit-Tests mit Sample-Result schreiben.

Akzeptanz:

- Dry-Run liefert `header`, `positions`, `warnings`, `errors`.
- Kein MSSQL-Zugriff noetig.
- Fehlende Pflichtfelder blockieren Live-Export.

### P0-002 Export-Journal

Status: offen

Ziel:

- VenDoc-Exporte dauerhaft in Postgres protokollieren.

Tasks:

- Migration `009_create_vendoc_export_jobs.sql`.
- Tabelle fuer Export-Jobs anlegen.
- `external_document_id` stabil speichern.
- Position-UUIDs stabil speichern oder deterministisch ableiten.
- Status und Fehler speichern.

Akzeptanz:

- Jeder Dry-Run und Live-Export ist nachvollziehbar.
- Re-Export kann kontrolliert entschieden werden.

### P0-003 VenDoc API

Status: offen

Ziel:

- API-Endpunkte fuer Dry-Run, Live-Export und Exporthistorie.

Tasks:

- `POST /vendoc/export/{document_id}?dry_run=true|false`
- `GET /vendoc/export-jobs/{document_id}`
- `GET /vendoc/export-jobs/{document_id}/latest`
- Fehlercodes fuer nicht freigegebene Dokumente.

Akzeptanz:

- Dry-Run funktioniert ohne MSSQL.
- Live-Export ist ohne Freigabe blockiert.

### P0-004 MSSQL Live-Write

Status: blockiert bis CIBEX-Zugang

Ziel:

- Freigegebene Dokumente in `SRTemp` schreiben.

Tasks:

- MSSQL-Client/ODBC-Strategie festlegen.
- Dockerfile um Treiber erweitern.
- Env-Variablen einbauen.
- Connection-Test implementieren.
- Transaktionalen Insert fuer Header und Positionen bauen.
- Fehler und Rollback testen.

Akzeptanz:

- Header und Positionen werden zusammen geschrieben.
- Bei Fehlern entsteht kein Teilimport.
- Export-Job zeigt Erfolg oder Fehler.

### P0-005 Freigabe-Gate fuer VenDoc

Status: offen

Ziel:

- Kein ungeprueftes Dokument geht ins ERP.

Tasks:

- Live-Export nur bei `document.status=processed`.
- Live-Export nur bei `approval_status=approved`.
- UI-Hinweis, warum Export gesperrt ist.

Akzeptanz:

- Nicht freigegebene Dokumente liefern HTTP `409`.
- UI zeigt konkrete Sperrgruende.

### P0-006 Canary wieder gruen

Status: erledigt am 2026-04-27

Ziel:

- `./infra/api-canary.sh` ist ein verlaesslicher Release-Gate.

Umgesetzt:

- Shared-Image-Fallback fuer Positionen ohne brauchbare Alternative.
- Same-page Page-All-Fallback, wenn fokussierte Kandidaten nur schwache Folgeseitenbilder enthalten.
- Provider-Validierung so geschaerft, dass fachliche Info-/Gruppenpositionen nicht als harte Betragsfehler zaehlen.

Akzeptanz:

- `./infra/api-canary.sh` laeuft gruen fuer `alu_one`, `entholzer`, `rieder`, `sr_schauraum`, `newo` und `rekord_vomp`.

## P1 - Produktion

### P1-001 Auth und Rollen

Status: offen

Tasks:

- Login oder Basic Auth.
- Rollen `operator`, `reviewer`, `admin`.
- Freigabe/Export nur fuer passende Rollen.
- Auditfelder fuer User-Aktionen.

### P1-002 Background Jobs

Status: offen

Tasks:

- `process_jobs` Tabelle.
- Worker fuer Processing.
- Persistenter Progress.
- Dokument-Lock.
- Retry/Cancel.

### P1-003 Feldkorrekturen

Status: offen

Tasks:

- Kopffelder in UI editierbar machen.
- Positionen in UI editierbar machen.
- Summen korrigieren oder neu berechnen.
- Korrekturen auditieren.

### P1-004 Betrieb

Status: offen

Tasks:

- Docker Healthchecks.
- Readiness fuer Postgres/Storage/MSSQL.
- Backup/Restore dokumentieren.
- Strukturierte Logs.
- TLS/Reverse Proxy.
- Secrets-Handling.

### P1-005 API modularisieren

Status: offen

Tasks:

- Router aus `api/main.py` extrahieren.
- Pydantic Response-Modelle.
- Fehlerformat vereinheitlichen.

## P2 - UX und Ausbau

### P2-001 Review-Queue

Status: offen

Tasks:

- Hauptansicht nach Status.
- Filter nach Anbieter, Datum, Fehler.
- Exportstatus in Liste.

### P2-002 Batch-Workflow

Status: offen

Tasks:

- Multi-PDF Upload.
- Batch-Processing.
- Batch-Export fuer freigegebene Dokumente.

### P2-003 Neue PDFs einarbeiten

Status: laufend, aktueller Schuchter/Muigg-Paketstand eingearbeitet

Tasks:

- Neue PDFs nach `samples/pdfs/candidates/offers/<anbieter>/`.
- Parser-Ergebnisse analysieren.
- Tests erweitern.
- Regression-Set und Provider-Matrix aktualisieren.

Aktueller erledigter Stand:

- 6 Schuchter-Angebote als gruene Kandidaten aufgenommen.
- 4 Muigg-Auftragsbestaetigungen als Nicht-Angebote aufgenommen.
- 4 technische SR-Schauraum-Detailansichten als Nicht-Angebote aufgenommen.
- Konkrete Dokumentenanforderung an Daniela steht in `docs/DANIELA_DOCUMENT_REQUEST.md`.
- Betrags-/Summenvalidierung fuer alle 39 Angebots-PDFs per `tests/test_offer_validation_smoke.py` abgesichert.

Naechster Dokumentenbedarf:

- komplette Projektpakete statt isolierter Einzel-PDFs.
- mehr SR-Schauraum-Angebote und falls vorhanden SR-Schauraum-ABs.
- weitere Schachermayer-Offerte/ABs.
- Rekord-Vomp-ABs, falls ABs importiert werden sollen.
- Anbieterpakete mit separaten Bildern, Elementuebersichten, Schnitten und Detailzeichnungen.

### P2-004 Bildworkflow verbessern

Status: offen

Tasks:

- Provider-spezifische Bildpflicht.
- `no_image_required` als Zustand.
- Schnellere UI fuer Bildkandidaten.
- VLM nur fuer Review-Faelle optional nutzen.
