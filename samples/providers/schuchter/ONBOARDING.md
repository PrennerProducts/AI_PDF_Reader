# Provider Onboarding: SCHUCHTER Fenster GmbH

Provider key: `schuchter`

## Created paths
- `api/template_schuchter.py`
- `samples/pdfs/regression/offers/schuchter/`
- `samples/pdfs/candidates/offers/schuchter/`

## Known corpus today
- Offer candidates:
- `samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260079.pdf`
- `samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260151.pdf`
- `samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260172.pdf`
- `samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260343.pdf`
- `samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260344.pdf`
- `samples/pdfs/candidates/offers/schuchter/schuchter__angebot__A260396.pdf`
- Existing non-offer references:
- `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26020.pdf`
- `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26021.pdf`
- `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26028.pdf`

## Next steps
1. Pick 1 to 3 canonical Schuchter PDFs and promote them to `samples/pdfs/regression/offers/schuchter/` once the regression set is intentionally expanded.
2. Add a stronger canonical regression to `tests/test_template_regression.py` when a representative PDF is promoted.
3. Keep future Schuchter variants in `samples/pdfs/candidates/offers/schuchter/` until they add real layout coverage.
4. Run the corpus tests after each new Schuchter PDF.

## Verification
```bash
python -m pytest tests/test_template_regression.py tests/test_offer_corpus_smoke.py tests/test_non_offer_corpus_smoke.py -q
./infra/api-canary.sh
```
