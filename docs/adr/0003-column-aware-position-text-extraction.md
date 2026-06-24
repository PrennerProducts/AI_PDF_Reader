# Ziel-Architektur: spaltenbasierte Extraktion des Positionstexts

**Status:** proposed (Ziel-Richtung). Aktueller Stand: Regex-Bereinigung pro
Template (siehe ADR 0002) als funktionierender Zwischenstand.

Die Belege sind Tabellen mit den Spalten
`Pos. | Menge EH | Bezeichnung | Einzelpreis | Gesamtpreis`. Heute liest der
Parser flache Textzeilen (`get_text("text", sort=True)`), wodurch Inhalte aus
Nachbarspalten in den Positionstext „bluten" — Zeichnungsmaße von links
(Pos./Menge) und Preise von rechts (E-/G-Preis). Diese werden anschließend per
Regex wieder entfernt.

**Entscheidung (Ziel):** Den Beschreibungstext **spaltenbewusst** extrahieren —
die Tabellenspalten über ihre x-Grenzen erkennen und den Langtext nur aus dem
Band der Spalte **Bezeichnung** lesen (x ≥ Bezeichnung-Start, x <
Einzelpreis-Start), über `get_text("words")` mit x-Koordinaten. Damit kommen
Maße und Preise gar nicht erst in den Text, statt sie nachträglich zu putzen.

**Warum:** systematisch (eine Mechanik statt Heuristik je Anbieter),
generalisiert über alle spaltenbasierten Angebote, robuster. Teilt die Primitive
**Tabellen-/Spaltenerkennung** mit dem Bild-Crop (ADR-loses Detail:
`_description_column_left_pt` erkennt bereits die Bezeichnung-Spalte für den
Bildausschnitt; für den Text zusätzlich die Einzelpreis-Grenze).

**Trade-offs / Konsequenzen:**
- Größerer Eingriff in die Text-Extraktion als die Regex-Bereinigung.
- Ändert den **Textinhalt** für alle Anbieter → anbieterübergreifend
  verifizieren. Der Export-Contract-Test schützt nur die *Struktur*, nicht den
  Inhalt; daher Property-Tests je Anbieter (kein Maß-/Preis-Leak) ergänzen.
- Bis zur Umsetzung bleibt ADR 0002 (Regex) der gültige Zwischenstand.

Umsetzung als eigener, getesteter Slice (PRD 0001).
