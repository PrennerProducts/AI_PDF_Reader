# Projekt-Dokumentation

Stand: 2026-04-29

Diese Doku ist der zentrale Einstieg fuer Planung, Status, Architektur, API und VenDoc-Integration.

## Aktive Dokumente

- `docs/PLAN.md`: priorisierter Umsetzungsplan bis zur produktionsreifen App.
- `docs/STATUS.md`: aktueller technischer und fachlicher Stand.
- `docs/PRODUCTION_READINESS.md`: Release-Gates, Checklisten und Risiken fuer Produktivbetrieb.
- `docs/TASKS.md`: konkrete Umsetzungstasks mit Prioritaet und Akzeptanz.
- `docs/HOW_IT_WORKS.md`: technische Funktionsweise der aktuellen App.
- `docs/API.md`: API-Referenz inkl. Review/Freigabe und VenDoc-Dry-Run/Export-Journal.
- `docs/VENDOC_MSSQL_ACCESS_NOTES.md`: VenDoc/MSSQL-Zugriff, Dragan/CIBEX-Stand, Tabellenmapping.
- `docs/PROVIDER_ONBOARDING.md`: Ablauf fuer neue Anbieter-Templates und neue PDFs.
- `docs/DANIELA_DOCUMENT_REQUEST.md`: konkrete Anforderungsliste fuer weitere Parser-/VenDoc-Testdokumente.

## Sample- und Parser-Dokumente

- `samples/README.md`: Struktur des PDF-Korpus.
- `samples/OFFER_PROVIDER_MATRIX.md`: Providerstatus.
- `samples/REGRESSION_SET.md`: kanonische Regression und Kandidaten.
- `samples/providers/<anbieter>/ONBOARDING.md`: providerbezogene Notizen.

## Historische Feature-Docs

Diese Dateien sind als Verlauf/Initialplanung zu lesen. Der aktuelle Plan steht in `docs/PLAN.md`.

- `features/PROJ-1-poc-plan-roadmap.md`
- `features/PROJ-2-sql-schema-v1.md`
- `features/PROJ-3-abnahme-matrix-v1.md`
- `features/PROJ-4-sample-pdf-analysis-v1.md`

## Neue Angebotsdokumente

Neue PDFs bitte zuerst in den Kandidatenbereich einordnen:

```text
samples/pdfs/candidates/offers/<anbieter>/
```

Namensschema:

- Angebote: `<anbieter>__angebot__<dokumentnummer>.pdf`
- Auftragsbestaetigungen: `<anbieter>__auftragsbestaetigung__<dokumentnummer>.pdf`
- Technische Detail-/Planunterlagen: `<anbieter>__detailansicht__<objekt_oder_planref>.pdf`
- Anbieter kleinschreiben und Sonderzeichen vermeiden, zum Beispiel `schuchter`, `muigg`, `sr_schauraum`.

Danach:

1. Parser-Ergebnis pruefen.
2. Erwartete Felder und Positionszahl in Tests aufnehmen.
3. Nur stabile, repraesentative Varianten in `samples/pdfs/regression/offers/<anbieter>/` heben.
4. Provider-Matrix und Regression-Set aktualisieren.

## Wichtige Checks

```bash
python -m pytest tests/test_template_regression.py -q
python -m pytest tests/test_offer_corpus_smoke.py -q
python -m pytest tests/test_offer_validation_smoke.py -q
python -m pytest tests/test_non_offer_corpus_smoke.py -q
python -m pytest tests/test_validation_provider_rules.py -q
.venv/bin/python -m pytest tests -q
./infra/api-canary.sh
```
