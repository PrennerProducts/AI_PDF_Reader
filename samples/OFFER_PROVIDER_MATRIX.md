# Offer Provider Matrix

Stand: 2026-04-27

## Corpus Summary

- Angebots-PDFs gesamt: `39`
- Aktuell gruene Angebots-PDFs: `39`
- Noch offene neue Angebotslayouts: `0`
- Regression-Satz: `18` PDFs
- Zusätzliche grüne Kandidaten: `21` PDFs

## Provider Status

| Anbieter | Gruene Regression | Gruene Kandidaten | Aktueller Status | Hauptthema |
| --- | ---: | ---: | --- | --- |
| `rieder` | 3 | 1 | stabil | Angebotskorpus ist sauber von AB getrennt |
| `entholzer` | 3 | 2 | stabil | ältere AB-Variante ist jetzt als AB einsortiert |
| `newo` | 3 | 1 | stabil | kein akuter Parserblocker |
| `alu_one` | 2 | 3 | stabil | drei zusätzliche Angebotsvarianten liefern bereits grüne Parser-Ergebnisse |
| `rekord_vomp` | 3 | 0 | stabil | VAX-Korpus ist jetzt eigener Anbieter und grün |
| `sr_schauraum` | 1 | 0 | stabil | kein akuter Parserblocker |
| `koch` | 1 | 2 | stabil | 3 Angebots-PDFs mit eigenem Template und gruenem Korpus |
| `muigg` | 1 | 2 | stabil | Varianten in Klammern, Unterpositionen und neue ABs sind jetzt abgedeckt |
| `schachermayer` | 1 | 1 | stabil | tabellarische Offert-Layouts plus Kommissionsfallback laufen gruen |
| `schuchter` | 0 | 6 | stabil | sechs echte Angebots-PDFs plus vorhandene AB-Varianten laufen gruen |
| `schlotterer` | 1 | 2 | stabil | drei echte Angebots-PDFs plus vorhandene ABs liefern jetzt gruene Ergebnisse |

## Green Provider Set

### Rieder
- Regression: `samples/pdfs/regression/offers/rieder/`
- Kandidaten: `samples/pdfs/candidates/offers/rieder/`
- Parserstatus: alle `4` echten Angebots-PDFs liefern Positionen und vollständige Summen
- Hinweis: die älteren `Auftragsbestätigung`-Dateien liegen jetzt korrekt unter `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/rieder/`

### Entholzer
- Regression: `samples/pdfs/regression/offers/entholzer/`
- Kandidaten: `samples/pdfs/candidates/offers/entholzer/`
- Parserstatus: `5` echte Angebots-PDFs grün
- Hinweis: `12402032-10` ist jetzt fachlich korrekt als `Auftragsbestätigung` einsortiert

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
- Kandidaten: `samples/pdfs/candidates/offers/alu_one/`
- Parserstatus: `5` Angebots-PDFs grün, davon `3` zusätzliche Kandidaten
- Betriebshinweis: zur Sicherheit nach API-Neustarts einen echten Upload-Canary gegen `/process?...parser_only` laufen lassen, weil `pypdf`-Text und `pdftotext -layout` nicht immer identisch sind

### SR-Schauraum
- Regression: `samples/pdfs/regression/offers/sr_schauraum/`
- Parserstatus: aktuell grünes Einzeltemplate

### Koch
- Regression: `samples/pdfs/regression/offers/koch/`
- Kandidaten: `samples/pdfs/candidates/offers/koch/`
- Parserstatus: alle `3` Angebots-PDFs grün

### Muigg
- Regression: `samples/pdfs/regression/offers/muigg/`
- Kandidaten: `samples/pdfs/candidates/offers/muigg/`
- Parserstatus: alle `3` Angebots-PDFs grün, inklusive Varianten in Klammern und `001.1`-Unterpositionen
- AB: `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/muigg/`
- AB-Status: `4` neue Auftragsbestätigungen werden provider-spezifisch erkannt und positioniert

### Schachermayer
- Regression: `samples/pdfs/regression/offers/schachermayer/`
- Kandidaten: `samples/pdfs/candidates/offers/schachermayer/`
- AB: `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schachermayer/`
- Parserstatus: beide Offerte-PDFs plus die AB-Trennung sind jetzt sauber eingeordnet

### Schuchter
- Kandidaten: `samples/pdfs/candidates/offers/schuchter/`
- AB: `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schuchter/`
- Parserstatus: `6` echte Angebots-PDFs plus vorhandene ABs laufen gruen
- Hinweis: einige Schuchter-Angebote enthalten Positionsgruppen ohne Preiszeile; diese bleiben als Positionen erhalten und werden nicht aus dem Korpus gefiltert

### Schlotterer
- Regression: `samples/pdfs/regression/offers/schlotterer/`
- Kandidaten: `samples/pdfs/candidates/offers/schlotterer/`
- AB: `samples/pdfs/non_offer/auftrag_auftragsbestaetigung/schlotterer/`
- Parserstatus: alle `3` echten Angebots-PDFs plus die vorhandenen ABs liefern jetzt grüne Ergebnisse

## Pending Provider Set

Kein akuter Provider-Blocker im aktuellen Angebotskorpus.

## Test Commands

Gruener Gesamtkorpus:

```bash
python -m pytest tests/test_offer_corpus_smoke.py -q
python -m pytest tests/test_offer_validation_smoke.py -q
```

Starke Regressionen der kanonischen Layouts:

```bash
python -m pytest tests/test_template_regression.py -q
```

Vorhandene Nicht-Angebote:

```bash
python -m pytest tests/test_non_offer_corpus_smoke.py -q
```

## Priority Order

1. pro Anbieter einen echten Upload-Canary gegen die API fahren, damit `pypdf`-Extraktion und Testkorpus synchron bleiben
2. pro Anbieter weitere PDFs nur dann in den Regression-Satz heben, wenn sie einen echten Layout-Unterschied abdecken
3. nach jedem Anbieterblock den grünen Gesamtkorpus plus kanonische Regression laufen lassen

## Next Provider Watchlist

1. weitere neue Anbieter-/Layoutvarianten aus Danielas naechstem Paket
2. Anbieter mit komplexer Bildpflicht
3. AB-Layouts nur dort erweitern, wo sie fachlich in VenDoc importiert werden sollen
