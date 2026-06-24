# AI PDF Reader — Domänenmodell

Diese App liest Lieferanten-PDFs (Angebote/Auftragsbestätigungen), strukturiert
sie und exportiert sie in zwei Ziele. Auf den Export-Strukturen triggert ein
anderer Entwickler (Dragan) den Import ins ERP-System **VenDoc**.

> **Glossar, kein Spec.** Diese Datei definiert *Begriffe*, nicht Implementierung.
> Spalten/Schemata stehen im Code und in den verlinkten Dokumenten.
>
> Erster Entwurf aus Code-Lektüre — in einer `/grill-with-docs`-Runde mit dem
> Team zu schärfen. Mit ⚠️ markierte Einträge sind vermutete Absicht, noch zu
> bestätigen.

---

## ⛔ Export-Vertrag (Tabu-Zone)

Was in die Export-DBs geschrieben wird, ist ein **stabiler Vertrag** mit einem
externen Importer. Spaltennamen, Spalten-Reihenfolge und Tabellennamen dürfen
sich **nicht unbeabsichtigt** ändern.

- Eingefroren durch: `tests/test_export_contract.py`
- Abstimmung bei bewusster Änderung: `docs/VENDOC_DRAGAN_HANDOVER.md`

**Export Contract**:
Die Menge aus Tabellennamen, Spaltennamen und Spalten-Reihenfolge der beiden
Export-Ziele. Bewusste Änderung nur nach Abstimmung mit dem Importer + Update
des Freeze-Tests.
_Avoid_: "Export-Format", "Schema" (mehrdeutig)

**VenDoc-Export (SRTemp)**:
Schreibt Header + Positionen nach MSSQL (`dbo.vendoc_import_headers`,
`dbo.vendoc_import_positions`, DB `SRTemp`). Das ist das Ziel, auf dem Dragans
Import triggert.
_Avoid_: "ERP-Export", "MSSQL-Dump"

**Postgres-Export**:
Der eigene App-Export (`documents`, `line_items`, `document_amount_lines`,
`document_images`) als SQL/CSV/JSON via `exporter.py`.

**Live-Export vs. Dry-Run**:
Ein Live-Export schreibt tatsächlich nach SRTemp; ab dann gilt das Dokument als
in VenDoc importiert. Ein Dry-Run erzeugt nur das Skript/die Vorschau.
_Avoid_: "Test-Export" für Dry-Run

**Export Job**:
Ein Eintrag in `vendoc_export_jobs` (`document_id`, `dry_run`, `status`). Ein
erfolgreicher Live-Export ist `dry_run = false`, `status = 'exported'`; daran
hängt die Doppelimport-Warnung.

---

## Dokument

**Document**:
Ein eingelesenes Lieferanten-PDF mit Kopfdaten (Lieferant, Nummer, Datum,
Summen) und Positionen.
_Avoid_: "File", "Upload" (das ist die Rohdatei, nicht das strukturierte Dokument)

**Document Type**:
Art des Belegs — `angebot` (Default), `auftragsbestaetigung` oder
`detailzeichnung` (nur Template `koch_detail`). Aus dem Belegkopf erkannt;
fällt auf `angebot` zurück, wenn nichts passt.

**Supplier**:
Der Lieferant, der das PDF erstellt hat (Rieder, NeWo, Schlotterer, …).
_Avoid_: "Vendor", "Anbieter" uneinheitlich

**Supplier ID Alias**:
Abbildung eines normalisierten Lieferantennamens auf die feste VenDoc-Lieferanten-
nummer (`SUPPLIER_ID_ALIASES`). Bestimmt `supplier_id` im Export-Header.

**Customer**:
Der Endkunde des Belegs; wird in der UI gewählt und als `customer_id`
(aus `vendoc_customer_number`) mit exportiert.
_Avoid_: "Client", "Kundendaten" (das ist die VenDoc-View)

**Freigabe (Approval)**:
Geprüfter Gate vor dem Export: ein Dokument muss freigegeben sein
(`approval_status = 'approved'`, mit `reviewed_by`), bevor ein **Live-Export**
nach VenDoc erlaubt ist. Freigabe setzt voraus, dass das Dokument
freigabefähig ist (Validierung bestanden).
_Avoid_: "Bestätigung", "Review" (Review = der Prüfvorgang, Freigabe = das Ergebnis)

---

## Position

**Line Item / Position**:
Eine Zeile des Belegs. Intern aus dem PDF geparst; beim Export werden die
Positionsnummern **neu vergeben** (lückenlos), unabhängig von der PDF-Nummer.
_Avoid_: "Row", "Artikel" (Position ≠ einzelner Artikel)

**Alternative Position**:
Eine Position, die eine Variante zu einer Hauptposition ist (`is_alternative`).
_Avoid_: "Option", "Variante" austauschbar verwenden

**Alternativ-Angebot (is_alternate)**:
Header-Flag, getrennt vom Positions-Flag `is_alternative`. Code-Verhalten:
`is_alternate = true`, wenn **alle** Exportpositionen Alternativen sind (keine
Hauptposition übrig). Die fachliche Bedeutung (z. B. „der gesamte Beleg ist eine
Alternative zu einem anderen Angebot") ist **noch offen — mit Dragan/Team zu
klären**.
_Avoid_: `is_alternate` und `is_alternative` synonym verwenden

**Alternative Position Mode**:
Wie Alternativen einsortiert werden — `nested` (als Unterposition `1.1`, `1.2`
unter der Hauptposition) oder `append` (gesammelt am Ende, neu durchnummeriert).
_Avoid_: "Layout", "Sortierung"

**Embedded Alternative**:
Eine Alternative, die nicht als eigene Zeile, sondern als `Alternativ:`-Zeile im
Langtext (`description_long`) der Hauptposition steckt und beim Export
herausgelöst wird.

**Aggregated Alternative**:
Mehrere gleichartige Alternativen, die zu einer Position zusammengefasst werden
("Gesammelte Alternative …"). Schlotterer-Alternativen werden **nicht**
aggregiert.

**Positionstext**:
Kurztext (`description_short`) und Langtext (`description_long`) einer Position.
Müssen frei von Layout-Artefakten sein — keine Positions-/Flügelnummern,
Koordinaten, Referenzcodes oder Preise; legitime Maße bleiben. Bereinigt pro
Lieferanten-Template zur Parse-Zeit (siehe `docs/adr/0002-position-text-sanitization-per-template.md`).
_Avoid_: "Beschreibung" unqualifiziert (Kurz- vs. Langtext unterscheiden)

---

## Preise

**Unit Price (EP/VK)**:
Verkaufs-/Einzelpreis der Position, wie im Beleg ausgewiesen.
_Avoid_: "Preis" unqualifiziert

**Purchase Price (EK)**:
Einkaufspreis nach Abzug der Lieferanten-Konditionen — der Wert, den VenDoc als
EK übernimmt.
_Avoid_: "Kosten", "Nettopreis"

**Pricing Adjustments**:
Pro-Dokument-Schalter (`apply_pricing_adjustments`), ob die Lieferanten-
Konditionen auf den EK angewendet werden.
_Avoid_: "Rabatt-Modus"

**Pricing Sequence**:
Die geordnete Folge von Zu-/Abschlägen eines Lieferanten (z. B. Rieder:
+3 %, −38 %, −8 %, −8 %), die EP → EK überführt.
_Avoid_: "Rabattkette" uneinheitlich

**Sentinel Unit Price**:
Der feste Wert `999999.0`, der bei aktiven Pricing Adjustments als `unit_price`
exportiert wird. Bewusst „unmöglicher" Platzhalter: maßgeblich ist der EK aus
`purchase_price`; der auffällige VK verhindert, dass der Originalpreis
versehentlich als Verkaufspreis übernommen wird.
_Avoid_: "Dummy-Preis", "Fehlwert"

---

## Identität & Verknüpfung

**External Document ID / External Line Item ID**:
Deterministische UUID5 (fester Namespace) aus Dokument-/Positions-Identität.
Stabil über wiederholte Exporte — daher überschreibt ein Re-Export denselben
Datensatz statt einen neuen anzulegen.
_Avoid_: "Export-ID" unqualifiziert

**Source Line Item ID**:
Die Herkunfts-ID einer Exportposition (`vendoc_source_line_item_id` bzw.
Original-ID), inkl. zusammengesetzter IDs für aggregierte Alternativen.

**LV-Pos**:
Die eigene Leistungsverzeichnis-Nummer einer Position (Muster `NN.NN.NN.X`),
wie im Lieferantenbeleg ausgewiesen (`lv_pos`).
_Avoid_: "Positionsnummer" (das ist die fortlaufende `position_no`)

**Referenced LV-Pos**:
Verweis einer Position auf ihre **übergeordnete Kunden-LV-Position** — geparst
aus Text wie „zu Pos. 57.05.21.A" (`referenced_lv_pos`). Wird im Export als
`main_line_item_id` mitgegeben und unterdrückt die Bild-Pflicht der Position.
Aktuell nur bei NeWo befüllt.
_Hinweis_: Wie VenDoc `main_line_item_id` weiterverarbeitet, ist mit Dragan noch
abzustimmen (siehe `docs/VENDOC_MSSQL_ACCESS_NOTES.md`).
