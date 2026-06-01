# Production-Readiness-Plan

Stand: 2026-05-28

## Definition von produktionsreif

Die App gilt als produktionsreif, wenn folgende Punkte erfuellt sind:

- Upload, Verarbeitung, Review, Freigabe und VenDoc-Export laufen end-to-end stabil.
- Kein ungeprueftes Dokument kann in VenDoc geschrieben werden.
- Jeder Export ist auditierbar, retrybar und gegen Dubletten abgesichert.
- Fehler sind fuer Anwender sichtbar und fuer Entwickler nachvollziehbar.
- Das System ist auf dem Zielserver abgesichert, backupfaehig und ueberwachbar.
- Parser-Regressionen verhindern Rueckschritte bei bekannten Dokumentlayouts.

## Release-Gates

Vor jedem produktiven Release muessen diese Checks gruen sein:

```bash
python -m pytest tests/test_template_regression.py -q
python -m pytest tests/test_offer_corpus_smoke.py -q
python -m pytest tests/test_offer_validation_smoke.py -q
python -m pytest tests/test_non_offer_corpus_smoke.py -q
python -m pytest tests/test_validation_provider_rules.py -q
python -m pytest tests/test_exporter_approval.py -q
./infra/api-canary.sh
```

Hinweis: Der volle Host-Testlauf wurde zuletzt so ausgefuehrt:

```bash
env PYTHONPATH=api .venv/bin/python -m pytest tests -q
```

Stand 2026-05-28: `209 passed, 2 warnings`. Die Warnings sind FastAPI-Deprecation-Hinweise.

## Checkliste P0

- [x] VenDoc-Mapping als Dry-Run.
- [x] VenDoc-Live-Write in `SRTemp` im Code.
- [ ] VenDoc-Live-Write gegen Zielserver produktionsnah verifiziert.
- [x] Export-Journal `vendoc_export_jobs`.
- [x] Stabile externe UUIDs fuer Dokument und Positionen.
- [x] Re-Export-Warnung in der UI.
- [ ] Finale Re-Export-Regel mit Dragan/CIBEX entschieden.
- [x] Freigabe-Gate fuer VenDoc-Export auf API-Ebene.
- [x] MSSQL-Fehler sauber in UI/API sichtbar.
- [x] Live-Canary fachlich gruen.
- [x] Doku fuer CIBEX-Zugang und Env-Variablen aktuell.

## Checkliste P1

- [x] Authentifizierung.
- [ ] Rollen und Berechtigungen.
- [ ] Background Processing.
- [ ] Persistenter Processing-Fortschritt.
- [ ] Feldkorrektur in der UI.
- [x] Audit fuer User-Aktionen und manuelle Eingriffe.
- [ ] Healthchecks und Readiness.
- [ ] Backup-/Restore-Prozess.
- [ ] Strukturierte Logs.
- [ ] Secrets sauber ausserhalb des Repos.

## Checkliste P2

- [ ] Batch-Upload.
- [ ] Batch-Processing.
- [ ] Batch-Export fuer freigegebene Dokumente.
- [ ] Review-Queue als Hauptworkflow.
- [ ] Provider-spezifische Bildpflicht-Regeln.
- [ ] Neue Angebotsdokumente in Korpus und Regression.

## Risiken

### MSSQL-Zugriff

Der MSSQL-Zugriff muss pro Zielserver/VPN aktiv verifiziert werden. Ohne gueltige `.env` bleibt der Writer deaktiviert.

Massnahme:

- VenDoc-Dry-Run ist implementiert und kann ohne MSSQL-Zugang genutzt werden.
- `GET /vendoc/health?check_connection=true` vor Live-Write ausfuehren.
- Nach Live-Write per SQL-Select auf Header/Positionen gegen `external_document_id` pruefen.

### VenDoc-Feldregeln

Einige Spalten sind laut Dragan anders oder noch nicht final.

Massnahme:

- Mapping zentral kapseln.
- Ungeklaerte Felder als `NULL` oder konfigurierbare Defaults fuehren.
- Pflichtfeldpruefung erst nach finalem Spaltenvertrag schaerfen.

### Bildzuordnung

Die aktuelle Bildzuordnung ist fuer den Canary-Korpus gruen. Neue Layouts koennen trotzdem fachlich falsche oder fehlende Bildzuordnungen erzeugen.

Massnahme:

- Bildpflicht je Provider/Positionstyp trennen.
- `no_image_required` als eigener Zustand.
- Warnungen per Review aufloesbar halten.
- Neue Bildfallbacks nur mit Regressionstest aufnehmen.

### Parser-Varianz

Neue Angebotsdokumente koennen neue Layouts enthalten.

Massnahme:

- Neue PDFs zuerst als Kandidaten aufnehmen.
- Parser nur mit Regression erweitern.
- Provider-Matrix nach jedem Anbieter aktualisieren.

## Empfohlene Umsetzung in Sprints

### Sprint 1 - VenDoc Dry-Run und Doku

Ergebnis:

- Doku aktuell.
- Dry-Run-Mapping erzeugt VenDoc Header/Positionen.
- UI/API kann Mapping anzeigen.

### Sprint 2 - Export-Journal und Live-Write

Ergebnis:

- Exporte werden persistent geloggt.
- Live-Write gegen MSSQL ist im Code umgesetzt und muss am Zielserver abgenommen werden.
- Fehler und Retry sind sichtbar.

### Sprint 3 - Produktivhaertung

Ergebnis:

- Auth aktiv.
- Background Jobs aktiv.
- Backups und Healthchecks dokumentiert.

### Sprint 4 - Korpusausbau und UX

Ergebnis:

- Neue Angebotsdokumente sind eingearbeitet.
- Review-Queue und Batch-Workflow sind nutzbar.
