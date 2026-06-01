# Umsetzungstasks

Stand: 2026-05-28

Diese Liste ist der konkrete Backlog aus `docs/PLAN.md`.

## P0 - VenDoc und Release-Faehigkeit

### P0-001 VenDoc Dry-Run Mapper

Status: erledigt am 2026-04-29

Ziel:

- Aus einem `GET /result/{document_id}` Ergebnis einen VenDoc-kompatiblen Header-/Positionspayload bauen.

Tasks:

- `api/vendoc_exporter.py` erstellen.
- Header-Mapping implementieren.
- Positions-Mapping implementieren.
- Primaeres Bild als RTF/PNG-Hex anbinden.
- Pflichtfelder validieren.
- Unit-Tests mit Sample-Result schreiben.

Umgesetzt:

- `api/vendoc_exporter.py`.
- Deterministische externe UUIDs fuer Dokumente und Positionen.
- Header-/Positionsmapping gemaess Screenshot-Schema.
- Primaeres Positionsbild als RTF mit PNG-Hex.
- `warnings`/`errors`/`summary`.
- `tests/test_vendoc_exporter.py`.

Akzeptanz:

- Dry-Run liefert `header`, `positions`, `warnings`, `errors`.
- Kein MSSQL-Zugriff noetig.
- Fehlende Pflichtfelder blockieren Live-Export.

### P0-002 Export-Journal

Status: erledigt am 2026-04-29

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
- Re-Export-Regel ist fachlich noch offen; Jobs liefern dafuer externe IDs und Historie.

### P0-003 VenDoc API

Status: erledigt am 2026-04-29

Ziel:

- API-Endpunkte fuer Dry-Run, Live-Export und Exporthistorie.

Tasks:

- `POST /vendoc/export/{document_id}?dry_run=true|false`
- `GET /vendoc/export-jobs/{document_id}`
- `GET /vendoc/export-jobs/{document_id}/latest`
- `GET /vendoc/health`
- Fehlercodes fuer nicht freigegebene Dokumente.

Akzeptanz:

- Dry-Run funktioniert ohne MSSQL.
- Live-Export ist ohne Freigabe blockiert.

### P0-004 MSSQL Live-Write

Status: im Code umgesetzt, Zielserver-Abnahme offen

Ziel:

- Freigegebene Dokumente in `SRTemp` schreiben.

Tasks:

- MSSQL-Client/ODBC-Strategie festlegen. Status: erledigt mit ODBC Driver 18 + `pyodbc`.
- Dockerfile um Treiber erweitern. Status: erledigt.
- Env-Variablen einbauen. Status: erledigt.
- Connection-Test implementieren. Status: erledigt via `GET /vendoc/health?check_connection=true`.
- Transaktionalen Insert fuer Header und Positionen bauen. Status: erledigt.
- Fehler und Rollback testen. Status: technisch umgesetzt, gegen Zielserver noch zu pruefen.
- Zielserver-Live-Write mit VPN/MSSQL-Zugang gegen `SRTemp` ausfuehren. Status: offen.

Akzeptanz:

- Header und Positionen werden zusammen geschrieben.
- Bei Fehlern entsteht kein Teilimport.
- Export-Job zeigt Erfolg oder Fehler.

### P0-005 Freigabe-Gate fuer VenDoc

Status: erledigt

Ziel:

- Kein ungeprueftes Dokument geht ins ERP.

Tasks:

- Live-Export nur bei `document.status=processed`.
- Live-Export nur bei `approval_status=approved`.
- UI-Hinweis, warum Export gesperrt ist.
- UI-Import-State und Warnung vor erneutem Live-Import.

Akzeptanz:

- Nicht freigegebene Dokumente liefern HTTP `409`.
- UI zeigt konkrete Sperrgruende.

### P0-006 Canary wieder gruen

Status: erledigt, Stand 2026-05-28

Ziel:

- `./infra/api-canary.sh` ist ein verlaesslicher Release-Gate.

Umgesetzt:

- Shared-Image-Fallback fuer Positionen ohne brauchbare Alternative.
- Same-page Page-All-Fallback, wenn fokussierte Kandidaten nur schwache Folgeseitenbilder enthalten.
- Provider-Validierung so geschaerft, dass fachliche Info-/Gruppenpositionen nicht als harte Betragsfehler zaehlen.
- Canary um zwei Schuchter-Faelle erweitert.
- Canary meldet sich bei aktivierter App-Auth automatisch an.

Akzeptanz:

- `./infra/api-canary.sh` laeuft gruen fuer `alu_one`, `entholzer`, `rieder`, `sr_schauraum`, `newo`, `rekord_vomp`, `schuchter_composite` und `schuchter_accessory`.

## P1 - Produktion

### P1-000 UI/UX Redesign zur Operator-App

Status: in Arbeit

Ziel:

- Die UI von einer PoC-/Admin-Oberflaeche zu einer modernen, gefuehrten Operator-App umbauen.

Tasks:

- UX-Zielbild in `docs/UI_UX_REDESIGN.md` pflegen. Status: erledigt.
- Neue App-Shell ohne sichtbare PoC-Altlasten. Status: V3-Command-Bar mit stabilem Header, kleinem Schauraum-Logo und Admin-Menue umgesetzt.
- Gefuehrter Flow `Start -> Positionen -> Bilder -> Freigabe`.
- Overview als Entscheidungsscreen neu komponieren. Status: erster V3-Stand umgesetzt, Statusfarben auf ruhige Akzente reduziert.
- Positionen und Bilder als Review-Screens optimieren. Status: Positionen und Bilder erster V3-Stand umgesetzt.
- Freigabe als finalen Abschluss-Screen gestalten. Status: erster V3-Stand umgesetzt.
- Alte CSS-Schichten konsolidieren und entfernen. Status: `app-v2`-Schicht, Header-Collapse-Logik und V3-Collapse-Selektoren entfernt.

Akzeptanz:

- Ein Mitarbeiter erkennt sofort aktives Dokument, Status und naechsten Schritt.
- Technische Diagnose ist nicht Teil des Hauptflows.
- Upload/Verarbeitung/Freigabe sind ohne Erklaerung bedienbar.
- UI bleibt auf Desktop und kleineren Screens nutzbar.

### P1-001 Auth und Rollen

Status: Basis-Auth erledigt, Rollen offen/bewusst nicht aktiviert

Tasks:

- Login/Logout. Status: erledigt.
- Bootstrap-Benutzer per ENV. Status: erledigt.
- Setup-Registrierung fuer ersten Benutzer. Status: erledigt.
- Benutzeranlage im Admin-Bereich. Status: erledigt.
- Benutzeranzeige und Logout in der Kopfzeile. Status: erledigt.
- Auditfelder fuer User-Aktionen. Status: erledigt.
- Rollen `operator`, `reviewer`, `admin`. Status: offen; aktuell koennen alle angemeldeten Benutzer alles bedienen.
- Freigabe/Export nur fuer passende Rollen. Status: offen, nur relevant falls Rollenmodell fachlich gewuenscht ist.

### P1-002 Background Jobs

Status: offen

Tasks:

- `process_jobs` Tabelle.
- Worker fuer Processing.
- Persistenter Progress.
- Dokument-Lock.
- Retry/Cancel.
- Timeout-Fall `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/koch/49440_Auftragsbestätigung.pdf` analysieren: `/process` erzeugt Zwischendaten, laeuft aber laenger als der Client-Timeout.

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
- Betrags-/Summenvalidierung fuer alle Angebots-PDFs per `tests/test_offer_validation_smoke.py` abgesichert.
- Angebots-Smoke-Korpus am 2026-05-28: 39 Angebotsfaelle ueber 11 Anbieter, 0 Pflichtfeldfehler, 0 leere Positionslisten.
- Voller Host-Testlauf am 2026-05-28: `209 passed, 2 warnings`.

Naechster Dokumentenbedarf:

- komplette Projektpakete statt isolierter Einzel-PDFs.
- mehr SR-Schauraum-Angebote und falls vorhanden SR-Schauraum-ABs.
- weitere Schachermayer-Offerte/ABs.
- Rekord-Vomp-ABs, falls ABs importiert werden sollen.
- Anbieterpakete mit separaten Bildern, Elementuebersichten, Schnitten und Detailzeichnungen.

### P2-004 Bildworkflow verbessern

Status: laufend

Tasks:

- Provider-spezifische Bildpflicht.
- `no_image_required` als Zustand.
- Schnellere UI fuer Bildkandidaten.
- Bild-Review-Faelle manuell schneller aufloesbar machen.

Umgesetzt:

- PyMuPDF-Bildbloecke sind die produktive Quelle fuer eingebettete Bilder, weil sie sichtbare Bildrechtecke stabiler liefern als die alte manuelle `pypdf`-CTM-Erkennung.
- Die alte `pypdf`-CTM-Fallbackstrecke wurde entfernt; PyMuPDF ist verpflichtende Runtime-Abhaengigkeit.
- Kleine PyMuPDF-Header-/Logo-Fragmente werden direkt verworfen, damit sie nicht als Produktbilder im Review auftauchen.
- Schuchter-Line-Art-Ergaenzung: Positionsbloecke werden ueber `Pos. <Nr>` erkannt, links gerendert und als PNG-Bild gespeichert, wenn technische Linien erkannt werden.
- Schuchter-Line-Art-Crops werden auf die technische Zeichnung inklusive Bemaszung verfeinert; Positionskopf, Menge und Trennlinien werden aus dem Crop entfernt.
- `A260172` liefert dadurch 13 Vektor-Positionsbilder und 13/13 Bildzuordnungen.
- SR-Schauraum Software-/Servicepositionen werden als nicht bildpflichtig behandelt.
- Liefer-/Transport-/Kran-, Aufpreis-, Summen- und "bereits in Grundposition enthalten"-Zeilen werden als nicht bildpflichtig behandelt.

Offen:

- Line-Art-Ergaenzung an weiteren Schuchter-Angeboten und Detail-PDFs regressionstesten.
- Bildkarten im UI kompakter machen und Kandidaten/Finalbild schneller vergleichbar machen.
- Segmentierung fuer voll gerenderte Seiten als dritte Stufe pruefen, falls kuenftige PDFs weder Bildbloecke noch erkennbare Positions-Line-Art enthalten.

### P2-005 UI vereinfachen

Status: erster Schnitt erledigt am 2026-04-27

Umgesetzt:

- Grosser Hero-Header durch kompakte Operator-Leiste ersetzt.
- Sichtbarer Hauptflow reduziert auf Dokumentauswahl, Upload, Verarbeitung, Status, Pruefung und Freigabe.
- Parser-only ist der einzige sichtbare Verarbeitungsmodus.
- KI-/Debug-/Preview-Aktionen aus dem Hauptflow entfernt; Verarbeitung ist parser-only.
- Quellen-Tab aus sichtbarer Navigation entfernt.
- Tab-Leiste als Workflow-Stepper `Pruefung -> Aufgaben -> Positionen -> Bilder` mit Status-Badges und Hilfetext umgebaut.
- Extraktions-Tabs in den Panel-Header verschoben und auf `Uebersicht`, `Freigabe`, `Positionen`, `Bilder` reduziert.
- PDF-Auswahl startet Upload und Parser-Verarbeitung automatisch; der sichtbare `Verarbeiten`-Button bleibt als manueller Re-Run.
- Schauraum-Logo in der kompakten Topbar sichtbar gemacht.
- Benutzeranzeige und Logout in der sichtbaren Kopfzeile.
- App-styled Login-Dialog.
- Admin-Bereich mit vereinfachter Benutzeranlage per Benutzername und Passwort.
- Freigabe-Assistent mit konkreten Vor-Freigabe-Schritten eingebaut.
- Schritt-Aktionen springen direkt zu Aufgaben, Positionen, Bildern oder Freigabe.
- Kundenauswahl im Startbereich.
- Alternativpositionsmodus im Positionsbereich.
- Duplicate-Import-Warnung als App-Modal.

Offen:

- Review-Queue als Startscreen.
- Feldkorrekturen fuer Kopf und Positionen.
