# Wie das System funktioniert

Stand: 2026-04-29

## Uebersicht

Das System laeuft On-Prem und verarbeitet Angebots- und Auftragsbestaetigungs-PDFs in einer API-Pipeline. Die interne Persistenz liegt in Postgres. Fuer VenDoc ist ein zusaetzlicher MSSQL-Writer geplant, der freigegebene Dokumente in die externe Datenbank `SRTemp` schreibt.

## Komponenten

### API

Dateien:

- `api/main.py`
- `api/db.py`
- `api/exporter.py`

Aufgaben:

- Upload.
- Processing.
- Result/Preview/Export.
- Review und Freigabe.
- Bildzuordnung.
- Dokumentverknuepfung Angebot/Auftragsbestaetigung.
- UI-Auslieferung.

Hinweis:

- `api/main.py` ist aktuell gross und sollte fuer Production in Router aufgeteilt werden.

### Parser und Extraktion

Dateien:

- `api/parser.py`
- `api/structured_parser.py`
- `api/extractor.py`
- `api/template_*.py`

Aufgaben:

- Template-Erkennung.
- Kopfdaten.
- Summen.
- Positionen.
- PDF-Text.
- PDF-Bilder.
- Seitenreferenzen.

Aktuelle Template-Anbieter:

- `alu_one`
- `entholzer`
- `koch`
- `muigg`
- `newo`
- `rekord_vomp`
- `rieder`
- `schachermayer`
- `schlotterer`
- `schuchter`
- `sr_schauraum`

### Dokumentverknuepfung

Dateien:

- `api/db.py`
- `api/parser.py`

Aufgabe:

- Angebote speichern ihre erkannte `document_number`.
- Auftragsbestaetigungen speichern ihre erkannte `offer_reference`.
- Nach der Verarbeitung setzt `refresh_document_links` bei passenden Lieferanten und Referenzen `linked_offer_document_id`.
- `GET /relations/{document_id}` und `GET /result/{document_id}` liefern die Verknuepfung mit.

Produktionshinweis:

- Die Verarbeitung ist parser-only. Es werden keine Cloud-Dienste, externen APIs oder KI-Modelle fuer die Extraktion genutzt.

### Postgres

Tabellen:

- `documents`
- `document_amount_lines`
- `line_items`
- `document_images`
- `vendoc_export_jobs`
- `schema_migrations`

Geplant:

- optional `document_corrections` oder Audit-Tabelle fuer manuelle Feldkorrekturen.

### Storage

Verzeichnisse:

- `data/uploads`: Original-PDFs.
- `data/logs/extracted_text`: Textdumps.
- `data/logs/extracted_images`: extrahierte Bilder.
- `data/exports`: erzeugte JSON/CSV/SQL-Dateien.

## Workflow

### 1. Upload

`POST /upload`

- PDF wird unter `/data/uploads` gespeichert.
- Dokument wird in Postgres mit `status=uploaded` angelegt.

### 2. Processing

`POST /process/{document_id}`

Schritte:

1. Status auf `processing`.
2. PDF-Text extrahieren.
3. PDF-Bilder aus echten Render-Placements extrahieren.
4. Parser-Template erkennen.
5. Kopfdaten, Summen und Positionen extrahieren.
6. Daten in Postgres schreiben.
7. Angebot/Auftragsbestaetigung verknuepfen.
8. Bildzuordnung berechnen.
9. Status auf `processed` oder `failed`.

Aktuelle Grenze:

- Processing laeuft synchron im HTTP-Request.
- Fortschritt liegt in-memory.
- Fuer Production soll daraus ein persistenter Background Job werden.

### 3. Validierung

`GET /result/{document_id}`

Beim Ergebnisabruf wird Validierung aufgebaut:

- Pflichtfelder.
- Empfohlene Felder.
- Summenkonsistenz.
- Positionsfelder.
- Seitenreferenzen.
- Bildzuordnung.
- Provider-Sonderregeln.
- Freigabe-Eignung.

Statuswerte:

- `auto_accept`: keine offenen Fehler/Warnungen.
- `manual_checked`: Warnungen wurden manuell geprueft.
- `review`: offene Warnungen.
- `reject`: offene Fehler.

### 4. Review

In der UI kann der Anwender:

- Auffaellige Positionen filtern.
- Bildkandidaten pruefen.
- Ein finales Bild setzen.
- Bewusst "kein Bild" setzen.
- Warnungen als manuell geprueft markieren.
- Dokument freigeben.

### 5. Export

Aktuell:

- JSON.
- CSV.
- SQL fuer das interne App-Schema.
- VenDoc-Dry-Run-Mapping mit Export-Journal.

Noch nicht umgesetzt:

- Direkter VenDoc-MSSQL-Write.

Geplanter VenDoc-Export:

1. Dokument muss verarbeitet sein.
2. Dokument muss freigegeben sein.
3. Mapping ist als Dry-Run pruefbar.
4. Export-Journal speichert Dry-Runs, Sperrgruende und Fehler.
5. Live-Write schreibt Header und Positionen spaeter in einer Transaktion, sobald MSSQL-Zugriff und Feldregeln final sind.

## Bildextraktion und Bild-Mapping

### Bildextraktion

- Quelle: PyMuPDF-Text-/Bildbloecke mit sichtbaren Layout-Koordinaten.
- Kleine Header-/Logo-Fragmente werden verworfen.
- Vektorbasierte Positionszeichnungen werden ueber gerenderte Line-Art-Ausschnitte als Bildkandidaten ergaenzt.
- Die alte `pypdf`-Content-Stream-Fallbackstrecke wird nicht mehr verwendet.

### Bildzuordnung

Felder pro Position:

- `image_ids`: finale Bildzuordnung.
- `image_ids_primary`: primaeres Bild.
- `image_candidate_ids`: Kandidaten.
- `image_ids_page_all`: alle Bilder derselben Seite.
- `image_assignment_source`: Quelle der Entscheidung.
- `image_assignment_reason`: Grund der Entscheidung.

Aktuelle Grenze:

- Bildzuordnung ist heuristisch.
- Fachliche Bildpflicht je Provider/Positionstyp muss noch schaerfer konfigurierbar werden.

## UI

Die UI ist aktuell eine Single-File-App unter `api/ui/index.html`.

Vorhanden:

- Upload.
- Dokumentliste.
- Processing.
- PDF-Viewer.
- Cockpit.
- Review.
- Positionen.
- Bilder.
- Preview/Download.
- Freigabe.

Fuer Production geplant:

- Review-Queue als Hauptscreen.
- Batch-Upload und Batch-Processing.
- VenDoc-Exportstatus.
- Feldkorrekturen.
- Rollen und Berechtigungen.

## VenDoc-Zielarchitektur

Interne App:

- Postgres bleibt fuehrend fuer Verarbeitung, Review, Freigabe und Audit.

Externe Ziel-DB:

- Microsoft SQL Server.
- Datenbank `SRTemp`.
- Tabellen:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`

Regel:

- VenDoc-Writer ist ein Zusatzmodul, kein Ersatz fuer Postgres.
- Live-Write nur nach Freigabe.
- Jeder Write wird in Postgres protokolliert.

## Bekannte Grenzen

1. VenDoc-MSSQL-Writer fehlt noch.
2. Authentifizierung fehlt noch.
3. Processing ist noch nicht als persistenter Job umgesetzt.
4. Feldkorrekturen in der UI fehlen noch.
5. Neue Angebotsdokumente muessen kontrolliert in Kandidaten und Regression einsortiert werden.
