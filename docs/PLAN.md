# Umsetzungsplan zur produktionsreifen App

Stand: 2026-04-29

## Zielbild

Die App soll produktiv als On-Prem-System laufen und Angebots-PDFs so verarbeiten, dass freigegebene Dokumente kontrolliert in den VenDoc-Import geschrieben werden koennen.

Zielprozess:

1. PDF hochladen oder gesammelt importieren.
2. Dokument serverseitig verarbeiten.
3. Parser-, Bild- und Summenvalidierung pruefen.
4. Fachliche Korrekturen und Bildzuordnungen in der UI vornehmen.
5. Dokument manuell freigeben.
6. Freigegebenes Dokument in die externe MSSQL-Importdatenbank `SRTemp` schreiben.
7. Exportstatus, Fehler und Re-Exports dauerhaft nachvollziehen.

## Aktueller Stand

Bereits umgesetzt:

- Docker-Stack fuer API, Postgres und Ollama.
- Upload, Reset, Processing, Progress, Result, Preview und Export.
- Template-Parser fuer die aktuellen Angebotsanbieter.
- Regression-Korpus fuer Angebote und Auftragsbestaetigungen.
- Bildextraktion aus echten PDF-Render-Placements.
- Heuristische Bildzuordnung plus optionaler VLM-Matcher.
- Validierung fuer Pflichtfelder, Summen, Positionen, Seitenreferenzen, Bilder und Provider-Sonderregeln.
- UI-Workbench mit PDF-Vorschau, Cockpit, Review, Positionen, Bildern, LLM-Historie und manueller Bild-/Review-Freigabe.
- Dokumentfreigabe (`approval_status`) als API- und UI-Funktion.
- VenDoc-Dry-Run-Mapping mit Export-Journal und API-Endpunkten.

Noch nicht produktionsreif:

- Kein echter MSSQL-Live-Writer fuer VenDoc.
- Keine Authentifizierung/Rollen.
- Processing laeuft synchron im Request statt als robuster Job.
- Doku und OpenAPI-Vertraege brauchen nach Codeaenderungen weiterhin Pflege.

## P0 - Muss vor dem Produktivbetrieb

### 1. VenDoc-MSSQL-Export implementieren

Ziel: Freigegebene Dokumente in die externe Datenbank `SRTemp` schreiben.

Status:

- Dry-Run-Mapping ist umgesetzt.
- Live-Write bleibt blockiert bis CIBEX-Zugang und finale Feldregeln vorliegen.

Tasks:

- Neues Modul `api/vendoc_exporter.py` fuer Mapping und Dry-Run. Status: erledigt.
- MSSQL-Client-Abhaengigkeit auswaehlen und einbauen.
- SQL-Server-Treiber im API-Dockerfile installieren.
- Env-Konfiguration ergaenzen:
  - `VENDOC_MSSQL_HOST`
  - `VENDOC_MSSQL_PORT`
  - `VENDOC_MSSQL_DATABASE=SRTemp`
  - `VENDOC_MSSQL_USER`
  - `VENDOC_MSSQL_PASSWORD`
  - `VENDOC_MSSQL_ENCRYPT`
  - `VENDOC_MSSQL_TRUST_SERVER_CERTIFICATE`
- Mapping auf `dbo.vendoc_import_headers` und `dbo.vendoc_import_positions` implementieren. Status: Dry-Run erledigt, Live-Write offen.
- `dry_run=true` unterstuetzen, damit Mapping und Pflichtfelder ohne echten Write geprueft werden koennen. Status: erledigt.
- Echtes Schreiben in einer Transaktion umsetzen: Header und Positionen entweder zusammen erfolgreich oder gar nicht.
- Fehler sauber zur API/UI zurueckgeben.

### 2. Export-Journal in Postgres

Ziel: Jeder VenDoc-Export muss nachvollziehbar und retrybar sein.

Status: umgesetzt fuer Dry-Runs und geblockte Live-Exportversuche.

Tasks:

- Migration fuer `vendoc_export_jobs` anlegen.
- Pro Export speichern:
  - `document_id`
  - `external_document_id`
  - Status (`pending`, `dry_run_ok`, `exported`, `failed`)
  - Zielserver/Zieldatenbank
  - Fehlertext
  - Anzahl Positionen
  - Exportzeitpunkt
  - Freigabedaten
- Stabile UUIDs je Dokument und Position speichern, damit Re-Exports keine neuen IDs erzeugen.
- Re-Export-Regel festlegen: blockieren, upsert oder Delete+Insert.

### 3. API-Endpunkte fuer VenDoc

Ziel: Separater ERP-Export statt Zweckentfremdung von `GET /export`.

Status: umgesetzt.

Tasks:

- `POST /vendoc/export/{document_id}?dry_run=true|false`
- `GET /vendoc/export-jobs/{document_id}`
- `GET /vendoc/export-jobs/{document_id}/latest`
- Optional: `GET /vendoc/health` fuer MSSQL-Verbindungstest.

Regel:

- Live-Export nur erlauben, wenn `document.status=processed` und `approval_status=approved`.
- Dry-Run darf auch vor Freigabe moeglich sein, muss aber klar als nicht geschrieben markiert werden.

### 4. VenDoc-Fachmapping finalisieren

Ziel: Keine spaeten Reworks durch unklare Importregeln.

Offen mit Dragan/CIBEX:

- Sind `dbo.vendoc_import_headers` und `dbo.vendoc_import_positions` final?
- Welche Spalten sind Pflichtfelder?
- Wie behandelt VenDoc Dubletten?
- Darf dieselbe `external_document_id` erneut importiert werden?
- Werden Alternativpositionen importiert?
- Werden `0,00`-Positionen importiert?
- Wie werden Bilder erwartet: Base64, Dateipfad oder separater Datensatz?
- Was bedeuten `tax_type`, `vat_type`, `unity`, `item_type`, `main_line_item_id` fachlich?
- Soll `line_total` in VenDoc nachgezogen werden? Aktuell fehlt diese Spalte in der Screenshot-Struktur.

### 5. Live-Canary als Release-Gate halten

Ziel: Reproduzierbarer Release-Gate.

Aktueller Befund:

- `.venv/bin/python -m pytest tests -q`: `165 passed`.
- Alle 39 Angebots-PDFs sind bei Betrags-/Summenvalidierung ohne Bildpflicht `auto_accept`.
- `./infra/api-canary.sh` ist am 2026-04-29 gruen fuer `alu_one`, `entholzer`, `rieder`, `sr_schauraum`, `newo` und `rekord_vomp`.

Tasks:

- Canary vor jedem Merge/Deployment laufen lassen.
- Neue Provider- oder Bildregeln nur mit Regressionstest aufnehmen.
- Fachlich erlaubte Review-Faelle explizit dokumentieren, statt Canary stillschweigend aufzuweichen.

## P1 - Production Hardening

### 1. Authentifizierung und Rollen

Tasks:

- UI und API schuetzen.
- Mindestens Rollen: `operator`, `reviewer`, `admin`.
- Freigabe und VenDoc-Export nur fuer berechtigte Rollen.
- Auditdaten speichern: wer hat verarbeitet, korrigiert, freigegeben, exportiert.

### 2. Processing als Job-System

Tasks:

- `process_jobs` Tabelle einfuehren.
- Processing aus HTTP-Request in Background Worker verschieben.
- Dokument-Lock gegen parallele Verarbeitung.
- Persistenter Fortschritt statt nur In-Memory-Progress.
- Saubere Retry-/Cancel-Logik.

### 3. Feldkorrekturen in der UI

Tasks:

- Kopfdaten editierbar machen.
- Positionen editierbar machen: Menge, Einheit, Beschreibung, Einzelpreis, Gesamtpreis, Seite, Alternative.
- Summen editierbar oder neu berechenbar machen.
- Jede manuelle Korrektur auditieren.
- Validierung nach jeder Korrektur neu berechnen.

### 4. Betrieb und Infrastruktur

Tasks:

- Healthchecks in Docker Compose fuer API/Postgres/Ollama.
- Readiness-Check fuer Postgres, Storage und optional MSSQL.
- Backup-Plan fuer Postgres und `data/uploads`.
- Logrotation und strukturierte Logs.
- TLS/Reverse Proxy fuer Serverbetrieb.
- Secrets nicht in `.env` im Repo ablegen.
- CPU-only Servermodus als Standard fuer Start dokumentieren.

### 5. API-Struktur verbessern

Tasks:

- `api/main.py` in Router aufteilen:
  - documents
  - processing
  - review
  - exports
  - vendoc
  - llm
- Pydantic Response-Modelle fuer stabile API-Vertraege.
- Fehlercodes und Fehlermeldungen vereinheitlichen.

## P2 - UX und fachlicher Ausbau

### 1. Review-Queue statt reine Workbench

Tasks:

- Startscreen mit Statuslisten:
  - hochgeladen
  - verarbeitet
  - pruefung erforderlich
  - freigabefaehig
  - freigegeben
  - exportiert
  - export fehlgeschlagen
- Filter nach Anbieter, Status, Datum, Fehlerart.
- Batch-Auswahl fuer Verarbeitung und Export.

### 2. Neue Angebotsdokumente einarbeiten

Tasks:

- Neue PDFs zuerst nach `samples/pdfs/candidates/offers/<anbieter>/`.
- Pro Anbieter 1 bis 3 kanonische PDFs in Regression heben.
- Parser nur mit Tests erweitern.
- `samples/OFFER_PROVIDER_MATRIX.md` und `samples/REGRESSION_SET.md` aktualisieren.
- Nach jedem Anbieter:
  - `python -m pytest tests/test_offer_corpus_smoke.py -q`
  - `python -m pytest tests/test_template_regression.py -q`
  - `./infra/api-canary.sh`

### 3. Bildworkflow verbessern

Tasks:

- Bildpflicht je Provider/Positionstyp konfigurierbar machen.
- `no_image_required` fachlich von `unmatched` unterscheiden.
- UI fuer Bildkandidaten schneller bedienbar machen.
- Optional: VLM-Matching nur fuer Review-Faelle statt fuer alle Positionen.

## Milestones

### M1 - Aktueller Stand stabilisieren

Akzeptanz:

- Doku aktuell.
- Lokale Tests in eingerichteter Python-Umgebung gruen.
- API-Canary gruen.

### M2 - VenDoc Dry-Run

Akzeptanz:

- Dry-Run erzeugt Header/Positionspayload fuer VenDoc.
- Pflichtfelder werden vor Write geprueft.
- UI zeigt Mapping-Preview und Fehler.

### M3 - VenDoc Live-Write

Akzeptanz:

- Live-Export schreibt in `SRTemp`.
- Transaktion funktioniert.
- Export-Journal dokumentiert Erfolg/Fehler.
- Re-Export-Regel ist implementiert.

### M4 - Produktivbetrieb

Akzeptanz:

- Auth aktiv.
- Backup/Restore getestet.
- Health/Readiness ok.
- Freigabe-Workflow end-to-end getestet.
- Mindestens 20 repraesentative Angebotsdokumente laufen stabil.

## Naechste konkrete Schritte

1. Zugriffsdaten von CIBEX abwarten und MSSQL-Verbindungsart klaeren.
2. UI-Button, Mapping-Preview und Statusanzeige fuer VenDoc-Dry-Run einbauen.
3. Re-Export-/Dublettenregel mit Dragan/CIBEX finalisieren.
4. MSSQL-Client/Treiber und transaktionalen Live-Write bauen.
5. Neue Angebots-PDFs in `candidates` aufnehmen und Parser-Korpus erweitern.
6. Canary nach jeder Parser-, Validierungs- oder Bildworkflow-Aenderung als Release-Gate laufen lassen.
