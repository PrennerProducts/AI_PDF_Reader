# Provider Onboarding

Dieses Repo hat jetzt einen festen Onboarding-Pfad fuer neue Angebotsanbieter.

## Scaffold

```bash
./infra/new-provider.sh muster_anbieter "Muster Anbieter GmbH"
```

Das legt an:
- `api/template_muster_anbieter.py`
- `samples/pdfs/regression/offers/muster_anbieter/`
- `samples/pdfs/candidates/offers/muster_anbieter/`
- `samples/providers/muster_anbieter/ONBOARDING.md`

Und es traegt den Anbieter direkt in `api/template_registry.py` ein.

## Erwarteter Ablauf

1. Neue PDFs zuerst nach `samples/pdfs/candidates/offers/<anbieter>/`.
2. 1 bis 3 kanonische Angebots-PDFs nach `samples/pdfs/regression/offers/<anbieter>/`.
3. In `api/template_<anbieter>.py` umsetzen:
- `detect()`
- `refine_headers()`
- `count_positions()`
- `extract_line_items()`
4. Regressionen nachziehen:
- `tests/test_offer_corpus_smoke.py`
- `tests/test_template_regression.py`
5. Statusmatrix aktualisieren:
- `samples/OFFER_PROVIDER_MATRIX.md`
6. API-Livepfad pruefen:
- `./infra/api-canary.sh`

## Mindestkriterien bevor ein Anbieter gruen ist

- Template wird eindeutig erkannt.
- `supplier_name`, `document_number`, `document_date` und `project_ref` sind stabil.
- Positionenzahl passt fuer die kanonischen PDFs.
- Netto, MwSt und Gesamt werden korrekt erkannt.
- Die Tests und der Live-Canary bleiben gruen.
