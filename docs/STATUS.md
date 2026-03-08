# Projektstatus

## Zuletzt aktualisiert
2026-02-26

## Erledigt
1. Docker-Compose Basis fuer API, Ollama und Postgres steht.
2. API-Stub mit Health-Endpunkt laeuft.
3. Feature- und Abnahme-Notizen sind angelegt.
4. 3 echte Kunden-PDFs wurden ins Repo uebernommen (`samples/pdfs/`).
5. Textdumps fuer Parser-Tests sind erzeugt (`samples/text/`).
6. Erste Analyse fuer ERP-relevante Felder ist dokumentiert (`features/PROJ-4-sample-pdf-analysis-v1.md`).
7. Docker-Smoke-Test erfolgreich:
- `docker compose up -d` startet `api`, `ollama`, `db`
- API Healthcheck `GET /health` liefert `200`
- Ollama `GET /api/tags` erreichbar
- Postgres antwortet auf Testquery (`select 1`)
8. AP1 Infra-Bereinigung:
- Port/Doku konsistent auf Host-Port `11435`
- GPU-Passthrough im Compose aktiviert
- GPU im Ollama-Container verifiziert (`/dev/nvidia*` vorhanden)
9. Parser-Start umgesetzt:
- Neues Modul `api/parser.py` (Template-Erkennung + Basisfeld-Extraktion)
- Neuer Dev-Endpunkt `POST /dev/parse-text` in `api/main.py`
- Smoke-Test gegen 3 Sample-Textdumps erfolgreich (Rieder/Entholzer/NeWo erkannt)
10. Ollama betriebsbereit mit Modell:
- `qwen2.5:7b-instruct` erfolgreich gepullt
- `/api/tags` listet das Modell
- Test-Generate erfolgreich (`response: OK`)
11. Upload + DB-Migrationen umgesetzt:
- Neues DB-Layer-Modul `api/db.py`
- Migrationen `api/migrations/001..005` fuer `documents`, `document_amount_lines`, `line_items`, `document_images`, Indizes
- Auto-Migration beim API-Startup
- Neuer Endpoint `POST /upload` mit Dateispeicherung nach `/data/uploads` und Insert in `documents`
- Neuer Endpoint `GET /documents`
- End-to-End-Test erfolgreich mit Sample-PDF (Dokument in DB + Datei im Upload-Volume)
12. Processing v1 umgesetzt:
- Neuer Endpoint `POST /process/{document_id}`
- PDF-Text-Extraktion via `pypdf` (`api/extractor.py`)
- Textdump nach `/data/logs/extracted_text/document_<id>.txt`
- Parser-Ergebnis wird in `documents` gespeichert (Lieferant, Nummer, Datum, Projekt, Summen, Confidence, Status)
- Erfolgreich mit Dokument 1 (Rieder), 2 (NeWo) und 3 (Entholzer) getestet
13. Ergebnisabruf umgesetzt:
- Neuer Endpoint `GET /result/{document_id}`
- Persistenz/Readout fuer `line_items`, `document_amount_lines`, `document_images`
14. Template-Parser erweitert:
- `structured_parser.py` mit supplier-spezifischen Heuristiken fuer Rieder, NeWo und Entholzer
- Robustere Summenzeilen-Erkennung inkl. Fallback fuer Netto/USt/Brutto
15. Export v1 umgesetzt:
- Neuer Endpoint `GET /export/{document_id}?format=json|csv|sql`
- Exporte werden nach `/data/exports` geschrieben und als Response ausgegeben
- SQL-Export erzeugt ERP-nahe Inserts fuer `documents`, `document_amount_lines`, `line_items`, `document_images`
16. Bildextraktion + Base64-Export:
- Beim Processing werden eingebettete PDF-Bilder extrahiert und in `document_images` gespeichert
- Bilddateien liegen unter `/data/logs/extracted_images/document_<id>/`
- JSON-Export kann Bilder als Base64 enthalten (`include_images_base64=true`)
17. Seiten-Mapping fuer Positionen:
- `line_items.page_ref` wird beim Parsing pro Position gefuellt
- Ergebnis liefert je Position `image_ids` und `image_count` (Bilder derselben Seite)
- CSV-Export enthaelt `page_ref`, `image_count`, `image_ids`
18. Web-Workbench fuer Abnahme/QA:
- Neuer UI-Endpunkt `GET /ui`
- Side-by-side Ansicht fuer PDF, Headerfelder, Betragszeilen, Positionen und Bilder
- Modal-Preview fuer JSON/CSV direkt in der UI (ohne neuen Browser-Tab)
- Direkte Streams fuer Originaldatei und Bilder:
  - `GET /document/{document_id}/file`
  - `GET /document/{document_id}/image/{image_id}`
- Neuer API-Preview-Endpunkt:
  - `GET /preview/{document_id}?format=json|csv`
19. Bildzuordnung v2 (Heuristik):
- `line_items.image_ids`/`image_count` zeigen jetzt primaer gemappte Bilder pro Position (statt alle Seitenbilder)
- Deko-Bilder werden heuristisch gefiltert (Duplikat-Hash, sehr klein in Flaeche/Bytes)
- Transparenz bleibt erhalten via `image_ids_page_all` und `image_count_page_all`
- Recall-first Mapping: pro Position werden mehrere Kandidaten geliefert (`current page` + Nachbarseiten), inkl. `image_ids_primary`
20. Bildextraktion v2 (Rotation + echte Placements):
- Bilder werden nur noch ueber tatsaechliche `Do`-Placements aus dem Content-Stream extrahiert (nicht mehr alle Resource-XObjects je Seite)
- Render-Transformation aus PDF-Matrix wird angewendet (u. a. vertikaler Flip bei negativem `d`)
- Ergebnis: deutlich weniger falsch zugeordnete Bilder und korrigierte Ausrichtung in der Vorschau
21. Doku-Refresh (Ist-Stand):
- `docs/HOW_IT_WORKS.md` auf realen Implementierungsstand gebracht
- `docs/PLAN.md` auf naechste Arbeitspakete ab aktuellem Stand umgestellt
- `docs/API.md` als kompakte API/Feld-Referenz neu angelegt
22. LLM-Integration (Ollama) in Processing:
- Neuer Modulpfad `api/llm.py` fuer JSON-basierte Feldextraktion via Ollama
- `POST /process/{document_id}` hat jetzt `use_llm` und `llm_override`
- Parser-first Merge: LLM fuellt standardmaessig nur fehlende Felder, Override optional
- LLM-Lauf wird je Dokument als Dump gespeichert (`/data/logs/llm/document_<id>.json`)
23. LLM-Processing v2 (Modi + Run-Transparenz):
- `POST /process/{document_id}` mit `process_mode` (`parser_only`, `hybrid_fill`, `llm_override`, `llm_only`)
- Backward-Compatibility fuer alte Query-Parameter bleibt erhalten
- Pro Lauf eigener Dump (`document_<id>_<run_id>.json`) + latest Alias
- Neue API fuer LLM-Runs:
  - `GET /llm-runs/{document_id}`
  - `GET /llm-runs/{document_id}/latest`
  - `GET /llm-runs/{document_id}/run/{run_id}`
- UI erweitert:
  - Modus-Selector statt LLM-Toggles
  - LLM-Run Tabelle mit `old/new/applied`
  - Buttons fuer `LLM Run JSON` und `LLM History`
24. Parser-vs-LLM Vergleich:
- Neuer Endpoint `GET /compare/{document_id}` (separater Parser-/LLM-Lauf, kein DB-Write)
- Feldvergleich inkl. `same/different/missing` Summary
- UI-Button `Parser vs LLM` mit JSON-Preview des Vergleichs
25. Bild-Matching PoC (VLM):
- Neuer Endpoint `POST /match-images/{document_id}` mit Strategien `heuristic|vlm|hybrid`
- Heuristik-Ranking bleibt als Fallback erhalten
- Vision-LLM nutzt Ollama Multimodal (`VLM_ENABLED`, `OLLAMA_VLM_MODEL`)

## Teilweise erledigt
1. Parser:
- Aktuell Skeleton/Regex-Basis; template-spezifische Positions- und Summenparser sind noch auszubauen.

## Offen
1. Validierungsregeln im Code
2. Tests/Regression auf Sample-PDFs
3. Praeziseres Objekt-Mapping Position <-> Bild (derzeit seitenbasiert)

## Risiken
1. Unterschiedliche Dokumentlayouts je Lieferant (template-spezifische Parser noetig)
2. Summen-/Rabattlogik pro Vorlage unterschiedlich
3. Unklare ERP-Feldregeln koennen Rework verursachen

## Naechste 3 Schritte
1. Validierungsflags (Summenkonsistenz, Pflichtfelder, Alternativpositionen) im Result mitgeben.
2. Testsuite fuer die 3 Sample-PDFs aufbauen (Parser + Export + Bildzuordnung).
3. Export-Mapping mit Kunde gegen ERP-Zieltabellen finalisieren (Pflichtfelder, Alternativpositionen, 0,00-Positionen).
