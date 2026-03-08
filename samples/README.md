# Sample PDFs for extraction tests

These files were copied into the project on 2026-02-26 for parser and ERP export testing.

## PDFs
- `samples/pdfs/AN Rieder F 20252082 BV Achhorner.pdf`
- `samples/pdfs/AN Enth neu 12502888-00_20250909_Email.pdf`
- `samples/pdfs/AN NEWO BVH Projekt 353 Achhorner.pdf`

## Text dumps (generated)
- `samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt`
- `samples/text/AN_Enth_neu_12502888-00_20250909_Email.txt`
- `samples/text/AN_NEWO_BVH_Projekt_353_Achhorner.txt`

## Regenerate text dumps
```bash
mkdir -p samples/text
pdftotext -layout "samples/pdfs/AN Rieder F 20252082 BV Achhorner.pdf" "samples/text/AN_Rieder_F_20252082_BV_Achhorner.txt"
pdftotext -layout "samples/pdfs/AN Enth neu 12502888-00_20250909_Email.pdf" "samples/text/AN_Enth_neu_12502888-00_20250909_Email.txt"
pdftotext -layout "samples/pdfs/AN NEWO BVH Projekt 353 Achhorner.pdf" "samples/text/AN_NEWO_BVH_Projekt_353_Achhorner.txt"
```

## Why these samples matter
- Different supplier templates (Rieder, Entholzer, NeWo)
- Different table styles for line items
- Discounts, surcharges, alternatives, and VAT blocks
- Embedded images available for image export testing
