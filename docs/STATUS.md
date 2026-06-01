# Projektstatus

Stand: 2026-05-28

## Kurzfazit

Die App ist eine fortgeschrittene On-Prem-Importfreigabe mit funktionaler Verarbeitung, Validierung, UI-Review, Login, Audit, VenDoc-Dry-Run und per ENV aktivierbarem MSSQL-Live-Writer. Fuer den Produktivbetrieb fehlen vor allem Zielserver-Verifikation des echten SRTemp-Writes, Rollen/Berechtigungen, robuste Background Jobs, Backups/Readiness und Feldkorrekturen in der UI. Der lokale Teststand ist gruen.

## Update seit Ende April 2026

- VenDoc-MSSQL-Live-Writer ist im Code umgesetzt und schreibt bei `VENDOC_MSSQL_ENABLED=true` transaktional nach `SRTemp`.
- Microsoft ODBC Driver 18 und `pyodbc` sind im API-Image vorbereitet.
- `GET /vendoc/health?check_connection=true` kann den echten MSSQL-Zugriff pruefen.
- UI warnt vor erneutem Live-Import, wenn ein Dokument bereits erfolgreich exportiert wurde.
- Kundensuche/-auswahl aus `SRTemp` ist im Startbereich verfuegbar; `customer_id` wird im Header exportiert.
- VenDoc-Kurztexte werden bereinigt, Langtexte behalten Gewichte/Umfangsangaben, und RTF-Felder fuer Text+Bild, nur Text und nur Bild werden erzeugt.
- Alternativpositionen koennen pro Dokument als `nested` oder `append` exportiert werden; Exportnummern werden lueckenlos neu vergeben.
- App-Auth ist implementiert: Login, Logout, Bootstrap-Benutzer, Admin-Benutzeranlage und Session-Cookies.
- UI zeigt den angemeldeten Benutzer in der Kopfzeile und bietet einen sichtbaren Logout.
- Audit-Log protokolliert Benutzeraktionen wie Upload, Processing, Bildzuordnung, Freigabe, Kundenzuordnung, Dry-Run, Live-Export und Reset.
- Canary kann sich bei aktivierter Auth automatisch anmelden.
- Aktueller Volltest: `209 passed, 2 warnings`.

## Aktuell umgesetzt

### Infrastruktur

- Docker Compose fuer API und Postgres.
- CPU-only Compose-Datei fuer Server ohne NVIDIA-GPU.
- Persistente Volumes fuer Postgres, Uploads, Exporte und Logs.
- Auto-Migrationen fuer Postgres beim API-Start.
- Live-Canary-Skript `./infra/api-canary.sh`.
- Microsoft ODBC Driver 18 im API-Image fuer SQL Server.

### API und Workflow

- Upload: `POST /upload`.
- Dokumentliste: `GET /documents`.
- Verarbeitung: `POST /process/{document_id}`.
- Fortschritt: `GET /progress/{document_id}`.
- Ergebnis: `GET /result/{document_id}`.
- Reset: `POST /reset/{document_id}`.
- Vorschau und Export: `GET /preview`, `GET /export`.
- Original-PDF- und Bildstreaming.
- Dokumentverknuepfung Angebot/Auftragsbestaetigung.
- Bild-Matching per lokaler Heuristik.
- Manuelle Bildzuordnung.
- Manuelle Positionspruefung.
- Dokumentfreigabe.
- VenDoc-Dry-Run-Endpunkt mit Header-/Positionsmapping.
- VenDoc-Live-Write nach `SRTemp`, per ENV schaltbar.
- VenDoc-Export-Journal mit Historie und letztem Exportversuch.
- VenDoc-Live-Gate: nicht verarbeitete oder nicht freigegebene Dokumente werden mit HTTP `409` blockiert.
- VenDoc-Import-State fuer UI-Anzeige und Doppelimportwarnung.
- Kundenauswahl fuer `SRTemp` inklusive `customer_id` im Exportheader.
- Dokumentweiter Alternativpositionsmodus fuer VenDoc-Export.
- Login/Logout, Bootstrap-Setup und Benutzeranlage.
- Audit-Events fuer relevante User- und Exportaktionen.

### Parser und Korpus

Aktuelle Anbieter-Templates im Angebots-Smoke-Korpus:

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

- 39 Angebotsfaelle ueber 11 Anbieter im Smoke-Korpus.
- Alle 39 Angebotsfaelle liefern Pflichtfelder, Summen und Positionslisten.
- 16 Non-Offer-/Auftragsbestaetigungsfaelle im Smoke-Korpus.
- Canary-Skript verarbeitet 8 repraesentative API-Faelle.
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
- Koch Detailzeichnungswarnung greift nur bei aktiver Bildvalidierung.
- SR-Schauraum Summen werden konsistent mit Euro-Prefix validiert.

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
- Sichtbare Benutzeranzeige mit Logout in der Kopfzeile.
- App-styled Login-Dialog.
- Admin-Bereich mit vereinfachter Benutzeranlage per Benutzername und Passwort.
- Kundenauswahl in `Start`.
- Alternativpositionsmodus in `Positionen`.
- Duplicate-Import-Warnung als App-Modal.

## Aktuelle Verifikation

Lokal ausgefuehrt am 2026-05-28:

```bash
env PYTHONPATH=api .venv/bin/python -m pytest tests -q
```

Ergebnis:

```text
209 passed, 2 warnings
```

Hinweis:

- Warnungen: FastAPI `on_event` ist deprecated; funktional kein Testfehler.
- `bash -n infra/api-canary.sh` ist sauber.
- `git diff --check` ist sauber.

Zusaetzlich abgesichert:

- Angebots-Smoke-Korpus: 39 Faelle, 0 Pflichtfeldfehler, 0 leere Positionslisten.
- Voller API-Robustheitslauf ueber 88 PDFs: 87 verarbeitet, 1 Timeout bei `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/koch/49440_Auftragsbestätigung.pdf`.
- Bekannte Rabatt-, Info- und Gruppenpositionen werden nicht mehr als harte Betragsfehler gewertet.
- Liefer-/Transport-/Kran-, Aufpreis-, Summen- und "bereits in Grundposition enthalten"-Zeilen loesen keine Bildpflicht mehr aus.
- Bildzuordnung fuer gleiche Seite ist abgesichert: Wenn fokussierte Kandidaten keine brauchbare gleiche-Seite-Option enthalten, wird `image_ids_page_all` in die Bewertung aufgenommen.
- Schuchter `A260172` wurde nach der Line-Art-Ergaenzung neu verarbeitet: 13 bereinigte Positionszeichnungen aus Vektor-Crops, 13/13 Positionen mit Bild, Validierung `auto_accept`.
- `sr_schauraum` Service-/Softwaremodule werden nicht mehr als bildpflichtige Produktpositionen bewertet.
- Persistierte `unmatched`-Bildentscheidungen mit unsicherem Auto-Match erzeugen keine offenen Bildpflichtwarnungen mehr, wenn keine belastbare automatische Zuordnung moeglich ist.

API-Runtime:

- Im API-Container kompilieren `main.py`, `db.py`, `vendoc_exporter.py`, `exporter.py`, `extractor.py`, `image_assignment.py` und `validation.py`.
- Migrationen bis inkl. App-User, Audit, Kundenzuordnung und Alternativmodus werden beim API-Start angewendet.

Live-Canary:

- Stack-Health wird ueber `GET /health` geprueft.
- `./infra/api-canary.sh` verarbeitet 8 API-Testdokumente:
  - `alu_one`
  - `entholzer`
  - `rieder`
  - `sr_schauraum`
  - `newo`
  - `rekord_vomp`
  - `schuchter_composite`
  - `schuchter_accessory`
- Der Canary unterstuetzt Login ueber `PDR_CANARY_USERNAME` / `PDR_CANARY_PASSWORD` oder Bootstrap-Creds aus `.env`.

## VenDoc/MSSQL Stand

Dragan/CIBEX-Stand:

- Datenbank: `SRTemp`
- Tabellen:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`
- SQL-Zugriff laeuft ueber VPN/CIBEX.
- Zielserver-Write muss je Deployment mit `GET /vendoc/health?check_connection=true` und anschliessendem SQL-Select geprueft werden.
- Einige Spalten/Detailregeln bleiben fachlich mit Dragan abzustimmen.

Im Code umgesetzt:

- VenDoc-Dry-Run-Mapping ohne MSSQL-Zugriff.
- Stabile deterministische externe UUIDs fuer Dokumente und Positionen.
- Export-Journal `vendoc_export_jobs`.
- API-Endpunkte fuer Dry-Run, Historie, letzten Job und Health.
- Live-Export-Gate fuer `processed` + `approved`.
- MSSQL-Connection-Konfiguration und ODBC-Health.
- Transaktionaler Live-Write nach `SRTemp`.
- Optionales SRTemp-SQL-Script im Dry-Run.
- Kundensuche, Kundenzuordnung und `customer_id` im Header.
- RTF-Export mit kombiniertem Text+Bild sowie optional Text-only/Bild-only.
- Alternativpositions-Exportmodi.

Noch nicht vollstaendig abgenommen:

- produktiver SRTemp-Live-Write am Zielsystem.
- finale Dubletten-/Re-Import-Regel mit Dragan/CIBEX.
- finale Regeln fuer optionale Spalten, Alternativen, Nullpositionen und Bilder.

## Wichtige offene Punkte

P0:

- Zielserver-Verifikation fuer VenDoc-MSSQL-Live-Write.
- Re-Import-/Dublettenregel finalisieren.
- Produktive `.env`/Secrets und Backup/Restore absichern.

P1:

- Rollen/Berechtigungen oder bewusste Entscheidung "alle angemeldeten Benutzer koennen alles".
- Processing als persistente Background Jobs.
- Feldkorrekturen in der UI.
- Betriebs-Readiness: Healthchecks, Backups, Logs, TLS, Secrets.

P2:

- Review-Queue und Batch-Workflow.
- Neue Angebotsdokumente in Korpus und Parser einarbeiten.
- Bildworkflow fachlich schaerfen.

## Naechste 5 Schritte

1. Auf dem Ubuntu-Zielsystem Pull/Rebuild mit `--env-file .env` und aktivierter Auth durchfuehren.
2. `GET /vendoc/health?check_connection=true` gegen den echten SQL Server pruefen.
3. Einen freigegebenen Beleg per Dry-Run und danach gezieltem Live-Write nach `SRTemp` testen.
4. SQL-Select auf `dbo.vendoc_import_headers` und `dbo.vendoc_import_positions` fuer die `external_document_id` machen.
5. Re-Import-/Dublettenregel mit Dragan finalisieren und neue reale PDFs weiter in Korpus/Regression aufnehmen.
