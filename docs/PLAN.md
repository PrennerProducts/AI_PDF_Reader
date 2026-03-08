# Umsetzungsplan ab Ist-Stand (2026-02-26)

## Zielbild
Stabile On-Prem PDF-Verarbeitung fuer Angebote mit:
- strukturierter Extraktion
- nachvollziehbarer Bildzuordnung
- ERP-faehigem Export (JSON/CSV/SQL)
- reproduzierbarer QA ueber Sample-PDFs

## Bereits umgesetzt
1. Infrastruktur laeuft (API, Ollama, Postgres, Volumes).
2. Upload, Processing, Result, Export, Preview und UI sind implementiert.
3. Migrationen + Persistenz fuer Kopf, Summen, Positionen und Bilder sind aktiv.
4. Template-Parser fuer Rieder, Entholzer und NeWo ist produktiv nutzbar.
5. Bildextraktion v2 (Do-Placement + CTM-Transformation) ist aktiv.
6. Optionaler LLM-Enrichment-Schritt (Ollama) ist in `POST /process` integriert.

## Naechste Arbeitspakete
### AP6 - Validierung und Datenqualitaet
Ziel: Ergebnisqualitaet messbar machen.
- Validierungsflags im Result einfuehren:
  - Pflichtfelder vorhanden/fehlend
  - Summenkonsistenz (Netto, VAT, Brutto)
  - Auffaellige Positionen (fehlende Preise/Mengen)
- Confidence-Regeln pro Bereich dokumentieren.

### AP7 - Bild-Mapping-Modi
Ziel: steuerbares Mapping je Anwendungsfall.
- Modus `precise`: 1 primaeres Bild je Position
- Modus `recall`: mehrere Kandidaten je Position
- Umschaltbar per API-Parameter und UI-Schalter
- Export muss gewaehlten Modus transparent mitgeben

### AP8 - Regression und Abnahme
Ziel: stabile Weiterentwicklung ohne Rueckschritte.
- Golden-Outputs fuer die 3 Sample-PDFs
- Tests fuer:
  - Parserfelder
  - Summenzeilen
  - Export-Formate
  - Bildzuordnung
- Abnahmecheckliste aus `features/PROJ-3-abnahme-matrix-v1.md` anbinden

### AP9 - ERP-Zielmapping finalisieren
Ziel: importfaehige, finale Exportvertraege.
- Feldmapping je Zieltabelle final abstimmen
- Pflichtfelder und Datentypen fixieren
- Umgang mit Alternativpositionen und 0,00-Positionen festlegen

## Milestones (aktualisiert)
1. M1 (done): Upload + Persistenz + Basisschema
2. M2 (done): Parser fuer 3 Haupttemplates
3. M3 (done): JSON/CSV/SQL Export + UI-Workbench
4. M4 (next): Validierungsflags + Regressionstests
5. M5 (next): ERP-Abnahme mit finalem Mapping

## Offene Entscheidungen mit Kunde
1. Welche Mapping-Variante soll Standard sein (`precise` oder `recall`)?
2. Sollen Alternativpositionen ins ERP geschrieben oder separat gefuehrt werden?
3. Wie sollen 0,00-Positionen im ERP behandelt werden?
4. Bilduebergabe: Base64 im Payload oder Dateireferenz?
5. Welche Summenfelder sind im ERP fuehrend?
