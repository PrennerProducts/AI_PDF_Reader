# Projektstatus

Stand: 2026-04-27

## Kurzfazit

Die App ist ein fortgeschrittener PoC mit funktionaler Verarbeitung, Validierung, UI-Review und Exporten. Fuer Produktionsreife fehlt vor allem der echte VenDoc-MSSQL-Schreibpfad, ein Export-Journal, Zugriffsschutz und robuste Job-Verarbeitung. Der Live-Canary ist aktuell wieder gruen.

## Aktuell umgesetzt

### Infrastruktur

- Docker Compose fuer API, Postgres und Ollama.
- CPU-only Compose-Datei fuer Server ohne NVIDIA-GPU.
- Persistente Volumes fuer Postgres, Uploads, Exporte und Logs.
- Auto-Migrationen fuer Postgres beim API-Start.
- Live-Canary-Skript `./infra/api-canary.sh`.

### API und Workflow

- Upload: `POST /upload`.
- Dokumentliste: `GET /documents`.
- Verarbeitung: `POST /process/{document_id}`.
- Fortschritt: `GET /progress/{document_id}`.
- Ergebnis: `GET /result/{document_id}`.
- Reset: `POST /reset/{document_id}`.
- Vorschau und Export: `GET /preview`, `GET /export`.
- Original-PDF- und Bildstreaming.
- LLM-Run-Historie und Parser-vs-LLM-Vergleich.
- Bild-Matching per Heuristik/VLM.
- Manuelle Bildzuordnung.
- Manuelle Positionspruefung.
- Dokumentfreigabe.

### Parser und Korpus

Aktuelle Anbieter-Templates:

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

Sample-Doku meldet:

- 39 gruene Angebots-PDFs.
- 18 PDFs im Regression-Satz.
- 21 zusaetzliche gruene Kandidaten.
- Auftragsbestaetigungen separat unter `samples/pdfs/non_offer/`.
- Neu einsortiert: 6 Schuchter-Angebote, 4 Muigg-Auftragsbestaetigungen und 4 technische SR-Schauraum-Detailansichten.

### Validierung und Review

Umgesetzt:

- Pflichtfelder auf Dokumentebene.
- Empfohlene Felder.
- Netto + USt = Brutto.
- Positionssummen und Komponentencheck.
- Provider-Sonderregeln fuer komplexe Preislogiken.
- Warnungen/Fehler pro Position.
- Bildzuordnungswarnungen.
- Manuelles Markieren von Warnungen als geprueft.
- Dokumentfreigabe nur bei `auto_accept` oder `manual_checked`.

### UI

Die UI unter `/ui` bietet:

- Dokumentauswahl und Upload.
- PDF-Vorschau.
- Processing-Modus-Auswahl.
- Cockpit mit Validierung.
- Review-Tab mit Freigabe.
- Positionsliste mit Details.
- Bildaudit und manuelle Bildzuordnung.
- JSON/CSV Preview.
- LLM-Run-Historie.
- Parser-vs-LLM-Vergleich.

## Aktuelle Verifikation

Lokal ausgefuehrt:

```bash
python -m pytest tests/test_template_regression.py tests/test_offer_corpus_smoke.py tests/test_offer_validation_smoke.py tests/test_non_offer_corpus_smoke.py tests/test_provider_offer_provisional.py tests/test_validation_provider_rules.py tests/test_exporter_approval.py tests/test_image_assignment_rebalance.py tests/test_image_preview_helpers.py -q
```

Ergebnis:

```text
130 passed
```

Zusaetzlich abgesichert:

- Alle 39 Angebots-PDFs laufen ohne Bildpflicht bei Betrags-/Summenvalidierung auf `auto_accept`.
- Bekannte Rabatt-, Info- und Gruppenpositionen werden nicht mehr als harte Betragsfehler gewertet.
- Bildfallback fuer gleiche Seite ist abgesichert: Wenn fokussierte Kandidaten keine brauchbare gleiche-Seite-Option enthalten, wird `image_ids_page_all` in die Bewertung aufgenommen.

Nicht vollstaendig lokal ausfuehrbar:

- `python -m pytest tests -q` bricht auf dem Host ab, weil `fastapi` in der lokalen Python-Umgebung fehlt.
- Im API-Container sind die Runtime-Abhaengigkeiten vorhanden; dort kompiliert `main.py`, `image_assignment.py`, `validation.py` und `db.py`.
- Der API-Container enthaelt aktuell kein `pytest`, daher wurde die neue Bildfallback-Regel zusaetzlich per direktem Runtime-Check geprueft.

Live-Canary:

- Stack laeuft und `GET /health` ist ok.
- `./infra/api-canary.sh` verarbeitet alle 6 Provider-Testdokumente.
- Ergebnis am 2026-04-27: `alu_one`, `entholzer`, `rieder`, `sr_schauraum`, `newo` und `rekord_vomp` liefern `validation=auto_accept`.

## VenDoc/MSSQL Stand

Dragan hat bestaetigt:

- Datenbank: `SRTemp`
- Tabellen:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`
- SQL-Zugriff wird durch CIBEX eingerichtet.
- Zugriffsdaten fehlen aktuell noch.
- Ein Datensatz mit Bildern soll vorbereitet werden.
- Einige Spalten sind laut Dragan anders oder noch nicht final; Detailabstimmung folgt nach Zugriff.

Im Code noch nicht umgesetzt:

- MSSQL-Verbindung.
- VenDoc-Mapping.
- Export-Journal.
- VenDoc-Dry-Run.
- VenDoc-Live-Write.
- UI-Anzeige fuer VenDoc-Exportstatus.

## Wichtige offene Punkte

P0:

- VenDoc-MSSQL-Dry-Run und Live-Write.
- Export-Journal und stabile externe UUIDs.
- Freigabe-Gate fuer VenDoc-Export.
- Re-Import-/Dublettenregel.

P1:

- Authentifizierung und Rollen.
- Processing als persistente Background Jobs.
- Feldkorrekturen in der UI.
- Betriebs-Readiness: Healthchecks, Backups, Logs, TLS, Secrets.

P2:

- Review-Queue und Batch-Workflow.
- Neue Angebotsdokumente in Korpus und Parser einarbeiten.
- Bildworkflow fachlich schaerfen.

## Naechste 5 Schritte

1. VenDoc-Dry-Run-Mapping ohne DB-Zugriff implementieren.
2. `vendoc_export_jobs` Migration und Exportstatus bauen.
3. UI um VenDoc-Preview/Exportstatus erweitern.
4. Nach CIBEX-Zugang echten MSSQL-Write aktivieren.
5. Neue Angebots-PDFs aufnehmen und Parser/Regression erweitern.
