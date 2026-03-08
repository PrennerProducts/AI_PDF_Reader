# Wie das System funktioniert (Ist-Stand)

## Uebersicht
Das System laeuft On-Prem und verarbeitet Angebots-PDFs in einer API-Pipeline.
Der aktuelle Stand ist produktionsnah fuer PoC/QA, mit Upload, Verarbeitung, Ergebnisausgabe, Export und Test-UI.

## Komponenten
1. API (`api/main.py`)
- Upload, Verarbeitung, Ergebnis- und Export-Endpunkte
- Web-Workbench unter `/ui`

2. Parser/Extractor (`api/parser.py`, `api/structured_parser.py`, `api/extractor.py`)
- Template-Erkennung (Rieder, Entholzer, NeWo)
- Kopfdaten, Summenzeilen, Positionen
- Bildextraktion inkl. Render-Transformationen

3. LLM Enrichment (`api/llm.py`, optional)
- Ollama-Aufruf fuer strukturierte Feld-Extraktion im JSON-Format
- Wird in `POST /process` ueber `process_mode` gesteuert
- Modi:
  - `parser_only`
  - `hybrid_fill` (parser-first)
  - `llm_override`
  - `llm_only`

4. Postgres (`api/db.py`, `api/migrations/*.sql`)
- Persistenz fuer Dokumentkopf, Betragszeilen, Positionen, Bilder

5. Storage (`data/`)
- `uploads/`: Original-PDFs
- `logs/extracted_text/`: Textdumps je Dokument
- `logs/extracted_images/`: extrahierte Bilder je Dokument
- `logs/llm/`: LLM-Run-Dumps je Lauf (`document_<id>_<run_id>.json`) + `document_<id>.json` als latest
- `exports/`: erzeugte Exportdateien

## API-Workflow
1. `POST /upload`
- Speichert PDF unter `/data/uploads/...`
- Legt Datensatz in `documents` an (`status=uploaded`)

2. `POST /process/{document_id}`
- Setzt `status=processing`
- Extrahiert PDF-Text mit `pypdf` (`\f` als Seiten-Trenner)
- Extrahiert Bilder aus echten `Do`-Placements im Content-Stream
- Wendet Render-Transformation aus der PDF-Matrix an (z. B. Flip)
- Parsed Kopfdaten, Summenzeilen, Positionen
- Optionaler LLM-Schritt je `process_mode`
- Schreibt pro Lauf einen LLM-Dump mit:
  - `parser_snapshot_before`
  - `parser_snapshot_after`
  - `changes` (Feld, old/new, applied)
- Schreibt Daten in `documents`, `document_amount_lines`, `line_items`, `document_images`
- Setzt `status=processed` oder `failed`

3. `GET /result/{document_id}`
- Liefert normalisierte Gesamtstruktur:
  - `document`
  - `amount_lines`
  - `line_items`
  - `images`

4. `GET /preview/{document_id}?format=json|csv`
- Liefert JSON/CSV direkt als Response
- Schreibt keine Export-Datei

5. `GET /export/{document_id}?format=json|csv|sql&include_images_base64=...`
- Erzeugt Exportinhalt
- Schreibt Datei nach `/data/exports`
- Gibt Inhalt direkt als Download-Response zurueck

6. `GET /ui`
- Side-by-side Testoberflaeche (Original-PDF, Extraction, Bilder, Preview-Modal)
- Modus-Auswahl fuer Process (`parser_only`, `hybrid_fill`, `llm_override`, `llm_only`)
- LLM-Run Tabelle (Parser vs LLM + applied ja/nein)
- LLM latest/history als JSON-Modal
- Parser-vs-LLM Vergleich als separater Lauf (Button `Parser vs LLM`, Endpoint `GET /compare/{document_id}`)
- Optionaler Bild-Matching-PoC: `POST /match-images/{document_id}` (heuristic/vlm/hybrid)

## Bildextraktion und Bild-Mapping
### Bildextraktion v2
- Quelle: PDF Content-Stream (`Do` Operator), nicht mehr nur Resource-Liste
- Vorteil: nur wirklich gezeichnete Bilder werden extrahiert
- Transformationen aus CTM werden auf das Bild angewendet (z. B. vertikal drehen/spiegeln)

### Mapping Position -> Bild
- `line_items.page_ref` wird beim Parsing gesetzt
- Mapping ist aktuell `recall-first`:
  - Kandidaten von aktueller Seite + Nachbarseiten
  - dekorative Bilder werden nur heuristisch gefiltert
- Felder pro Position:
  - `image_ids`: Kandidatenliste
  - `image_count`: Anzahl Kandidaten
  - `image_ids_primary`: erster primaerer Kandidat
  - `image_ids_page_all`: alle Bilder der Seite (Transparenz)
  - `image_count_page_all`: Anzahl aller Seitenbilder

## Datenmodell (Kurz)
1. `documents`
- Dokumentkopf, Summen, Status, Confidence, Pfade

2. `document_amount_lines`
- Summen-/Rabatt-/USt-Zeilen

3. `line_items`
- Positionen inkl. Mengen, Preisen, Seite, Confidence, Metadaten

4. `document_images`
- Bilder inkl. Seite, Index, Pfad, Hash, Groesse

## UI / QA-Workbench
Die UI unter `/ui` bietet:
- Dokumentauswahl und Re-Processing
- PDF-Viewer links, strukturierte Extraction rechts
- Positionen mit Bildkandidaten
- Bild-Thumbnails inkl. Metadaten
- JSON/CSV Preview im Modal (Copy/Download)
- Separate JSON/CSV Downloads

## Bekannte Grenzen
1. Bildzuordnung ist heuristisch, noch nicht objektgenau (Bounding-Box fehlt).
2. Parser ist template-spezifisch und muss fuer neue Layouts erweitert werden.
3. Validierungsflags (Pflichtfelder, Summenkonsistenz je Regelset) sind noch als eigener Arbeitsschritt offen.
