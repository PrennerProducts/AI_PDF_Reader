# PROJ-4: Sample PDF analysis + ERP extraction requirements (v1)

## Ziel
Auf Basis von 3 echten Kundenangeboten festlegen, was wir fuer eine robuste Extraktion und ERP-Speicherung benoetigen.

## Eingangsdateien
- `samples/pdfs/AN Rieder F 20252082 BV Achhorner.pdf` (5 Seiten)
- `samples/pdfs/AN Enth neu 12502888-00_20250909_Email.pdf` (18 Seiten)
- `samples/pdfs/AN NEWO BVH Projekt 353 Achhorner.pdf` (5 Seiten)

## Befund je Vorlage
1. Rieder
- Kopf: `Angebot: 20252082`, Datum, Kommission
- Positionen: `Position: <nr>` mit Details, Abschluss je Position als `EP ... GP ...`
- Summenblock: mehrere Zuschlaege/Abzuege (Teuerungszuschlag, Rabatt, Objektrabatt, Sonderrabatt), danach `Nettosumme`, `Mehrwertsteuer`, `Angebotssumme`
- Spezialfall: `Alternative` Position vorhanden

2. Entholzer
- Kopf: `Angebot 12502888.00`, Bauvorhaben/Kommission
- Positionen: `Pos.: <nr>` mit Mengen, B/H, LV-Pos, langer Beschreibungsblock
- Preise: EP/GP stehen pro Position am Ende der Position (nicht immer in Kopfzeile)
- Summenblock: `Summe ohne Montagekosten`, Rabatt, `Nettosumme`, VAT, `Angebotssumme`
- Spezialfall: `ALTERNATIV` Positionen vorhanden

3. NeWo
- Kopf: `Angebotsnummer: 25002995`, Kundennummer, Belegdatum, Kommission
- Positionen: numerische Positionscodes (`100`, `110`, ...), klare Mengen/EP/GP je Zeile
- Summenblock: `Zwischensumme`, `Mehrwertsteuer`, `Gesamtsumme`
- Spezialfall: Zeilen mit `0,00` und Referenz auf andere Positionen (`zu Pos.`)

## Was wir fuer das Auslesen brauchen
1. Template-Erkennung
- Regelbasiert pro Lieferant (Rieder/Entholzer/NeWo)
- Trigger woerter: `Angebot:`, `Angebot Nr`, `Angebotsnummer:`, `Pos.:`, `Position:`

2. Textvorverarbeitung
- `pdftotext -layout` als erster Schritt
- Entfernen von wiederkehrenden Kopf-/Fusszeilen
- Normalisieren von Leerzeichen und Zeilenumbruechen
- Zahlennormalisierung fuer DE/AT Format (`1 254,51`, `6.531,88`, `-EUR 4.425,67`)

3. Positionsparser (template-spezifisch)
- Startmarker pro Position erkennen
- Kopfwerte extrahieren: positionsnummer, menge, einheit, optional B/H
- Preiswerte extrahieren: einzelpreis, gesamtpreis
- Alternative Positionen markieren (`is_alternative`)
- Lange Produktdetails als strukturierte Attribute speichern (key/value wenn moeglich, sonst rohtext)

4. Summenparser
- Alle Betragzeilen als separate `amount_lines` erfassen
- Netto/VAT/Brutto final bestimmen
- Rabatte und Zuschlaege mit Vorzeichen speichern
- Running totals von Seitenkoepfen ignorieren (z. B. Entholzer)

5. Bildextraktion
- `pdfimages -list` zeigt eingebettete Bilder in allen 3 Samples
- Bilder seitenbezogen extrahieren und mit `document_id + page_no` referenzieren
- Fuer ERP: optional Base64 bei Export, im Storage besser als Datei/BLOB + Pfad

## ERP-freundliches Zielschema (minimal)
1. `documents`
- `id`, `source_file`, `supplier_name`, `customer_name`, `document_type`
- `document_number`, `document_date`, `project_ref`, `currency`
- `net_total`, `vat_total`, `gross_total`, `parse_confidence`, `status`

2. `document_amount_lines`
- `id`, `document_id`, `line_type` (`subtotal`, `discount`, `surcharge`, `vat`, `total`)
- `label_raw`, `percent`, `base_amount`, `amount`, `sort_order`

3. `line_items`
- `id`, `document_id`, `position_no`, `lv_pos`, `is_alternative`
- `quantity`, `unit`, `width_mm`, `height_mm`
- `description_short`, `description_long`
- `unit_price`, `line_total`, `page_ref`, `confidence`

4. `line_item_attributes`
- `id`, `line_item_id`, `attr_key`, `attr_value`
- Beispiel: `glasart`, `farbe`, `antrieb`, `pakethoehe`

5. `document_images`
- `id`, `document_id`, `page_ref`, `image_index`, `mime_type`, `storage_path`, `sha256`

## Validierungsregeln fuer ERP-Import
1. Summe(line_items.line_total) gegen relevante Zwischensumme pruefen
2. Netto + VAT == Brutto (Toleranz 0.02)
3. Mengen > 0, ausser ausdruecklich als info/option markiert
4. Waehrung einheitlich pro Dokument
5. Alternative Positionen duerfen nicht in Pflicht-Gesamtsumme laufen (konfigurierbar)

## Offene Fachfragen mit Kunde (vor Implementierung fixieren)
1. Sollen `ALTERNATIV` Positionen ins ERP geschrieben werden oder nur als Info?
2. Sollen `0,00` Positionen importiert werden?
3. Welche Summe ist im ERP fuehrend: `Zwischensumme`, `Nettosumme` oder `Angebotssumme`?
4. Werden detaillierte Positionsattribute im ERP benoetigt oder nur Kernfelder?
5. Soll Bildexport als Base64 in SQL passieren oder als Dateireferenz?

## Umsetzungsnaechste Schritte
1. Parser-Interfaces + supplier templates in Code aufsetzen
2. SQL schema migration fuer obige Tabellen erstellen
3. JSON/CSV/SQL exporter auf gemeinsames Normalformat bauen
4. Abnahme mit diesen 3 PDFs als erstes Regression-Set automatisieren
