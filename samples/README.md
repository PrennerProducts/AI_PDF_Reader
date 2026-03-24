# Sample PDFs for extraction tests

The PDF corpus is now split by purpose so parser work, regression coverage, and non-offer documents do not sit in one flat folder.

## Folder structure
- `samples/pdfs/regression/offers/`: canonical offer PDFs used for parser regression
- `samples/pdfs/candidates/offers/`: additional offer PDFs that are useful for expanding coverage
- `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/<anbieter>/`: provider-specific order confirmations and order documents
- `samples/pdfs/non_offer/grafik_technik/<anbieter>/`: provider-specific drawings, element overviews, and technical detail PDFs
- `samples/pdfs/duplicates/hashed_imports/`: duplicate copies with hash prefixes, kept only for traceability
- `samples/pdfs/inbox/raw_company_tree/`: temporary drop zone for raw provider folder imports before resorting
- `samples/pdfs/non_offer/`: non-offer documents that should not be mixed into offer-parser regression
- `samples/text/`: generated text dumps for selected canonical regression files

## Current regression set
- `samples/pdfs/regression/offers/rieder/AN Rieder F 20252082 BV Achhorner.pdf`
- `samples/pdfs/regression/offers/entholzer/AN Enth neu 12502888-00_20250909_Email.pdf`
- `samples/pdfs/regression/offers/newo/AN NEWO BVH Projekt 353 Achhorner.pdf`
- `samples/pdfs/regression/offers/rekord_vomp/Angebot_VAX60326.pdf`
- `samples/pdfs/regression/offers/sr_schauraum/Angebotsnr AN-2025-113 - SR Schauraum GmbH (2).pdf`
- `samples/pdfs/regression/offers/alu_one/Angebot A2602224MC.pdf`
- `samples/pdfs/regression/offers/alu_one/Angebot C2509283TB.pdf`

## Provider matrix
- `samples/OFFER_PROVIDER_MATRIX.md`: current green/red parser status by provider
- `samples/REGRESSION_SET.md`: canonical regression PDFs and candidate pool
- `samples/providers/<anbieter>/ONBOARDING.md`: generated checklist for newly scaffolded providers

## Existing text dumps
- `samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt`
- `samples/text/AN_Enth_neu_12502888-00_20250909_Email.txt`
- `samples/text/AN_NEWO_BVH_Projekt_353_Achhorner.txt`

## Regenerate text dumps
```bash
mkdir -p samples/text
pdftotext -layout "samples/pdfs/regression/offers/rieder/AN Rieder F 20252082 BV Achhorner.pdf" "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt"
pdftotext -layout "samples/pdfs/regression/offers/entholzer/AN Enth neu 12502888-00_20250909_Email.pdf" "samples/text/AN_Enth_neu_12502888-00_20250909_Email.txt"
pdftotext -layout "samples/pdfs/regression/offers/newo/AN NEWO BVH Projekt 353 Achhorner.pdf" "samples/text/AN_NEWO_BVH_Projekt_353_Achhorner.txt"
```

## Why these samples matter
- Different supplier templates: Rieder, Entholzer, NeWo, Rekord Vomp, SR-Schauraum, alu-one
- Different table styles for line items and totals
- Alternative positions, zero-value items, and VAT blocks
- Good base set for deterministic parser regression

## Test commands
```bash
python -m pytest tests/test_template_regression.py -q
python -m pytest tests/test_offer_corpus_smoke.py -q
```

## Add a new provider
```bash
./infra/new-provider.sh muster_anbieter "Muster Anbieter GmbH"
```

## Import a local company tree
```bash
cp -r ~/Documents/Schauraum_Angebote/* samples/pdfs/inbox/raw_company_tree/
```
