# PROJ-3: Abnahme-Matrix v1 (PoC)

## 1) Dokumentumfang (Testset)
- **Gesamt:** 40 PDFs
- **Verteilung:**
  - 15 Rechnungen
  - 15 Angebote
  - 10 Lieferscheine
- **Qualitätsmix:**
  - 70% gut lesbar (digital)
  - 20% mittel (Scan, leichte Artefakte)
  - 10% schwierig (schiefe/rauschige Scans)

## 2) Pflichtfelder (Must-Have)
### Kopfebene (pro Dokument)
- dokument_typ
- dokument_nummer (wenn vorhanden)
- datum
- waehrung
- gesamt_netto (wenn vorhanden)
- gesamt_brutto / gesamtsumme

### Positionsebene (pro Zeile)
- artikel_bezeichnung
- menge
- einheit (wenn vorhanden)
- einzelpreis
- gesamtpreis_zeile
- seitenreferenz

## 3) Zielmetriken (PoC-Abnahme)
### Feldgenauigkeit (Must-Have-Felder)
- **Kopf-Felder:** ≥ 95%
- **Positions-Felder:** ≥ 90%
- **Gesamtsummen-Konsistenz (Plausi):** ≥ 95%

### Dokument-Level
- **"PoC bestanden" pro Dokument**, wenn:
  - alle Pflicht-Kopffelder extrahiert ODER sauber als "nicht vorhanden" markiert
  - mindestens 90% der Positionen korrekt erfasst
  - Summencheck grün ODER sauber als "abweichend" markiert

### Performance (Richtwert für Demo)
- **Durchsatz:** Ø ≤ 20 Sekunden pro Dokument (40er Batch auf Zielsystem)

## 4) Validierungsregeln (v1)
1. Summe(Positionen) ~ Gesamtsumme (Toleranz 0.5% oder 0.02 Währungseinheiten)
2. Währung auf Kopf und Position darf nicht widersprüchlich sein
3. Menge > 0 (wenn Position erkannt)
4. Einzelpreis und Gesamtpreis numerisch parsebar
5. Seitenreferenz muss auf existierende Seite zeigen

## 5) Confidence-Policy
- confidence >= 0.85: **auto-accept**
- 0.60 bis < 0.85: **review empfohlen**
- < 0.60: **review erforderlich**

## 6) Export-Abnahme
- **JSON:** vollständige Struktur inkl. confidence + validation flags
- **CSV:** flache Positionstabelle für schnelle Sichtprüfung
- **SQL:** gegen v1-Zielschema validiert (INSERTs laufen fehlerfrei)

## 7) Go/No-Go für Meeting
- **GO**, wenn:
  - Zielmetriken erreicht oder knapp verfehlt mit klaren Gegenmaßnahmen
  - 5 repräsentative Demo-PDFs stabil laufen
  - Fehlerfälle transparent dokumentiert sind
- **NO-GO**, wenn:
  - Summen-/Positionsfehler systematisch auftreten
  - keine reproduzierbare Pipeline vorliegt

## 8) Offene Punkte für morgen (mit Kunde/IT klären)
1. SQL-Zielschema final (Tabellen/Felder/Constraints)
2. Priorität Netto vs Brutto als führende Summe
3. Umgang mit mehrsprachigen Dokumenten
4. Toleranzregeln für Rundungen im ERP
