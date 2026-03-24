# Offer Provider Matrix

Stand: 2026-03-24

## Corpus Summary

- Angebots-PDFs gesamt: `23`
- Aktuell gruene Angebots-PDFs: `23`
- Bekannte Problemgruppe: `0`
- Regression-Satz: `15` PDFs
- Zusätzliche grüne Kandidaten: `8` PDFs

## Provider Status

| Anbieter | Gruene Regression | Gruene Kandidaten | Aktueller Status | Hauptthema |
| --- | ---: | ---: | --- | --- |
| `rieder` | 3 | 4 | stabil | 3 ältere Kandidaten ohne `document_number` |
| `entholzer` | 3 | 3 | weitgehend stabil | 1 älterer Kandidat ohne `document_number` |
| `newo` | 3 | 1 | stabil | kein akuter Parserblocker |
| `alu_one` | 2 | 0 | stabil | nach API-Neustart immer Upload-Canary mitprüfen |
| `rekord_vomp` | 3 | 0 | stabil | VAX-Korpus ist jetzt eigener Anbieter und grün |
| `sr_schauraum` | 1 | 0 | stabil | kein akuter Parserblocker |

## Green Provider Set

### Rieder
- Regression: `samples/pdfs/regression/offers/rieder/`
- Kandidaten: `samples/pdfs/candidates/offers/rieder/`
- Parserstatus: alle `7` Angebots-PDFs liefern Positionen und vollständige Summen
- Offene Kopfwert-Lücke: `131584_Sevignani, zu 130629_3.pdf`, `132047_IB-Karlpassage_3.pdf`, `132475_Moonlight - Söll, zu 132207 + 132476_3.pdf` ohne `document_number`

### Entholzer
- Regression: `samples/pdfs/regression/offers/entholzer/`
- Kandidaten: `samples/pdfs/candidates/offers/entholzer/`
- Parserstatus: `6` reguläre Angebots-PDFs grün
- Offene Kopfwert-Lücke: `Angebot 12402032-10_20250415_Email.pdf` ohne `document_number`

### NeWo
- Regression: `samples/pdfs/regression/offers/newo/`
- Kandidaten: `samples/pdfs/candidates/offers/newo/`
- Parserstatus: alle `4` Angebots-PDFs grün

### Rekord Vomp
- Regression: `samples/pdfs/regression/offers/rekord_vomp/`
- Parserstatus: alle `3` bekannten `VAX`-Angebote grün
- Technischer Hinweis: die PDFs lagen vorher falsch unter Entholzer, parsern aber sauber über `rekord_vomp`

### alu-one
- Regression: `samples/pdfs/regression/offers/alu_one/`
- Parserstatus: beide Angebots-PDFs grün
- Betriebshinweis: zur Sicherheit nach API-Neustarts einen echten Upload-Canary gegen `/process?...parser_only` laufen lassen, weil `pypdf`-Text und `pdftotext -layout` nicht immer identisch sind

### SR-Schauraum
- Regression: `samples/pdfs/regression/offers/sr_schauraum/`
- Parserstatus: aktuell grünes Einzeltemplate

## Test Commands

Gruener Gesamtkorpus:

```bash
python -m pytest tests/test_offer_corpus_smoke.py -q
```

Starke Regressionen der kanonischen Layouts:

```bash
python -m pytest tests/test_template_regression.py -q
```

## Priority Order

1. fehlende `document_number` bei älteren `rieder`- und `entholzer`-Kandidaten nachziehen
2. pro Anbieter weitere PDFs nur dann in den Regression-Satz heben, wenn sie einen echten Layout-Unterschied abdecken
3. nach jedem Anbieterblock den grünen Gesamtkorpus plus kanonische Regression laufen lassen
