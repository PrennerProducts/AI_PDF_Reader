# Provider Onboarding: SCHUCHTER Fenster GmbH

Provider key: `schuchter`

## Created paths
- `api/template_schuchter.py`
- `samples/pdfs/regression/offers/schuchter/`
- `samples/pdfs/candidates/offers/schuchter/`

## Known corpus today
- No offer PDFs yet
- Existing non-offer references:
- `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26020.pdf`
- `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26021.pdf`
- `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/26028.pdf`

## Next steps
1. Put 1 to 3 canonical offer PDFs into `samples/pdfs/regression/offers/schuchter/`.
2. Put extra variants into `samples/pdfs/candidates/offers/schuchter/`.
3. Replace the placeholder detector and parsing logic in `api/template_schuchter.py`.
4. Add exact expectations for the new provider to `tests/test_offer_corpus_smoke.py`.
5. Add a stronger canonical regression to `tests/test_template_regression.py`.
6. Update `samples/OFFER_PROVIDER_MATRIX.md` after the provider is green.

## Verification
```bash
python -m pytest tests/test_template_regression.py tests/test_offer_corpus_smoke.py -q
./infra/api-canary.sh
```
