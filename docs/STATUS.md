# Projektstatus

Stand: 2026-04-29

## Kurzfazit

Die App ist ein fortgeschrittener PoC mit funktionaler Verarbeitung, Validierung, UI-Review, Exporten und VenDoc-Dry-Run. Fuer Produktionsreife fehlt vor allem der echte VenDoc-MSSQL-Schreibpfad, Zugriffsschutz und robuste Job-Verarbeitung. Der Live-Canary ist aktuell gruen.

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
- VenDoc-Dry-Run-Endpunkt mit Header-/Positionsmapping.
- VenDoc-Export-Journal mit Historie und letztem Exportversuch.
- VenDoc-Live-Gate: nicht verarbeitete oder nicht freigegebene Dokumente werden mit HTTP `409` blockiert.

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

Aktueller Sample-Stand:

- 41 Angebots-/Import-PDFs im API-Corpus.
- 38/41 Angebots-/Import-PDFs laufen aktuell auf `auto_accept`.
- 3/41 bleiben wegen offener Bildzuordnung auf `review`.
- 0/41 haben Pflichtfeldfehler.
- 0/41 liefern leere Positionslisten.
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
- Bild- und Textextraktion laufen produktiv ueber PyMuPDF; die alte `pypdf`-CTM-Fallbackstrecke wurde entfernt.
- Kleine Logo-/Headerfragmente werden bei der PyMuPDF-Extraktion verworfen.
- Positionsbasierte Vektor-Line-Art-Ergaenzung fuer Schuchter-Zeichnungen ohne eingebettete Rasterbilder.
- Schuchter-Line-Art wird innerhalb des Positionsblocks auf die technische Zeichnung mit Bemaszung verfeinert; Positionskopf und Mengenlabels werden aus dem Bildcrop entfernt.
- Manuelles Markieren von Warnungen als geprueft.
- Dokumentfreigabe nur bei `auto_accept` oder `manual_checked`.

### UI

Die UI unter `/ui` bietet:

- Laufendes UI/UX-Redesign ist in `docs/UI_UX_REDESIGN.md` dokumentiert; die V3-Command-Bar, der gefuehrte Pruefpfad, die Review-Screens und das Admin-Menue haben einen ersten modernen Stand.
- Kompakte Operator-Leiste statt grossem PoC-Header.
- Dokumentauswahl und Upload.
- PDF-Vorschau.
- Parser-only Verarbeitung als sichtbarer Standard.
- Uebersicht mit Validierung.
- Workflow-Stepper: `Pruefung`, `Aufgaben`, `Positionen`, `Bilder`.
- Extraktions-Tabs liegen im Panel-Header und sind auf `Uebersicht`, `Freigabe`, `Positionen`, `Bilder` reduziert.
- PDF-Auswahl startet Upload und Verarbeitung automatisch; sichtbarer Verarbeitungsbutton dient als Re-Run.
- Schauraum-Logo ist in der kompakten Topbar sichtbar.
- Freigabe im Aufgabenbereich.
- Freigabe-Assistent mit konkreten Schritten vor der Freigabe.
- Positionsliste mit Details.
- Bildaudit und manuelle Bildzuordnung.
- Diagnose-/Exportbereich ist eingeklappt und nicht Teil des Hauptflows.

## Aktuelle Verifikation

Lokal ausgefuehrt am 2026-04-29:

```bash
.venv/bin/python -m pytest tests -q
```

Ergebnis:

```text
165 passed
```

Hinweis:

- Der Host-Testlauf brauchte eine lokale `.venv`, weil global `fastapi` und `PyMuPDF` fehlten.
- Warnungen: FastAPI `on_event` ist deprecated; funktional kein Testfehler.

Zusaetzlich abgesichert:

- Finaler API-Corpuslauf fuer 41 Angebots-/Import-PDFs: 41 verarbeitet, 0 Fehler, 0 Pflichtfeldfehler, 0 leere Positionslisten, 3 Reviews wegen Bildzuordnung.
- Offene Angebots-Reviews:
  - `samples/pdfs/candidates/offers/alu_one/Angebot A2506340MC-1.pdf`: Pos. `003` ohne finales Bild.
  - `samples/pdfs/candidates/offers/muigg/AN 251073.pdf`: Pos. `002`, `003` ohne finales Bild.
  - `samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260344.pdf`: 0 extrahierte Bilder, Pos. `1` bildpflichtig.
- Voller API-Robustheitslauf ueber 88 PDFs: 87 verarbeitet, 1 Timeout bei `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/koch/49440_Auftragsbestätigung.pdf`.
- Bekannte Rabatt-, Info- und Gruppenpositionen werden nicht mehr als harte Betragsfehler gewertet.
- Liefer-/Transport-/Kran-, Aufpreis-, Summen- und "bereits in Grundposition enthalten"-Zeilen loesen keine Bildpflicht mehr aus.
- Bildzuordnung fuer gleiche Seite ist abgesichert: Wenn fokussierte Kandidaten keine brauchbare gleiche-Seite-Option enthalten, wird `image_ids_page_all` in die Bewertung aufgenommen.
- Schuchter `A260172` wurde nach der Line-Art-Ergaenzung neu verarbeitet: 13 bereinigte Positionszeichnungen aus Vektor-Crops, 13/13 Positionen mit Bild, Validierung `auto_accept`.
- `sr_schauraum` Service-/Softwaremodule werden nicht mehr als bildpflichtige Produktpositionen bewertet.
- Persistierte `unmatched`-Bildentscheidungen mit unsicherem Auto-Match erzeugen keine offenen Bildpflichtwarnungen mehr, wenn keine belastbare automatische Zuordnung moeglich ist.

API-Runtime:

- Im API-Container kompilieren `main.py`, `db.py`, `vendoc_exporter.py`, `exporter.py`, `extractor.py`, `image_assignment.py` und `validation.py`.
- Migration `009_create_vendoc_export_jobs.sql` wurde beim API-Start angewendet.

Live-Canary:

- Stack laeuft und `GET /health` ist ok.
- `./infra/api-canary.sh` verarbeitet alle 6 Provider-Testdokumente.
- Ergebnis am 2026-04-29: `alu_one`, `entholzer`, `rieder`, `sr_schauraum`, `newo` und `rekord_vomp` liefern `validation=auto_accept`.

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

Im Code umgesetzt:

- VenDoc-Dry-Run-Mapping ohne MSSQL-Zugriff.
- Stabile deterministische externe UUIDs fuer Dokumente und Positionen.
- Export-Journal `vendoc_export_jobs`.
- API-Endpunkte fuer Dry-Run, Historie, letzten Job und Health.
- Live-Export-Gate fuer `processed` + `approved`.

Im Code noch nicht umgesetzt:

- MSSQL-Verbindung.
- VenDoc-Live-Write.
- UI-Anzeige fuer VenDoc-Exportstatus.

## Wichtige offene Punkte

P0:

- VenDoc-MSSQL-Live-Write.
- Re-Import-/Dublettenregel.
- UI-Anzeige fuer VenDoc-Preview/Exportstatus.

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

1. UI um VenDoc-Preview/Exportstatus erweitern.
2. Nach CIBEX-Zugang echten MSSQL-Write aktivieren.
3. Re-Import-/Dublettenregel fachlich finalisieren.
4. Auth/Rollen und Audit fuer Freigabe/Export bauen.
5. Neue Angebots-PDFs aufnehmen und Parser/Regression erweitern.
