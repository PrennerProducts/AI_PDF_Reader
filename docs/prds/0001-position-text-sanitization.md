# PRD 0001 — Positionstexte anbieterübergreifend bereinigen

Verwandt: ADR `docs/adr/0002-position-text-sanitization-per-template.md`,
CONTEXT.md (Positionstext), `tests/test_schuchter_longtext.py`.

## Problem Statement

In den Positionstexten (Kurztext `description_short`, Langtext
`description_long`) landen Layout-Artefakte aus den PDFs: Positions-/
Flügelnummern, Kopplungs-/Koordinatenzahlen, Referenzcodes (z. B. `11.22.23`,
`22:`) und teils Preise. Dragan hat das für SCHUCHTER gemeldet (Doc #25 / lokal
#585: Kurztext `2-flg.Fenster, D/DK-Stulp 965 1000 .`, Langtext
`1 2 2-flg.Fenster … 965 1000` / `35 B/H: 1500x 1000`). Das Problem ist nicht
auf SCHUCHTER beschränkt — es kann **alle Lieferanten-Templates** betreffen und
verschmutzt die Daten, die in den VenDoc-Import gehen.

## Solution

Positionstexte werden so bereinigt, dass sie nur die echte Beschreibung und
legitime Maße enthalten — keine Layout-Zahlen/Preise. Die Bereinigung geschieht
**pro Lieferanten-Template zur Parse-Zeit** (siehe ADR 0002). Jeder Anbieter
wird geprüft und bei Bedarf angepasst, mit Tests je Anbieter. Bereits
gespeicherte Belege werden einmalig neu verarbeitet.

## User Stories

1. Als VenDoc-Importeur möchte ich Positionslangtexte ohne Layout-Zahlen, damit
   im ERP saubere Texte ankommen.
2. Als VenDoc-Importeur möchte ich Positionskurztexte ohne angehängte Maße/
   Nummern, damit Kurzbezeichnungen sauber sind.
3. Als Bearbeiter möchte ich, dass legitime Maße (`B/H:`, `bis 110`,
   `Aufdopplung 130`) erhalten bleiben, damit keine fachliche Information verloren geht.
4. Als Bearbeiter möchte ich, dass die Bereinigung pro Anbieter testbar ist,
   damit Regressionen auffallen, bevor sie exportiert werden.
5. Als Bearbeiter möchte ich bestehende Belege neu verarbeiten können, damit der
   Fix auch für schon importierte/gespeicherte Dokumente greift.
6. Als Entwickler möchte ich eine geteilte Filter-Bibliothek, damit nicht jeder
   Anbieter dieselbe Logik dupliziert (gemeinsame Helfer, pro Template aufgerufen).

## Implementation Decisions

- **Ziel-Architektur: spaltenbasierte Extraktion** (ADR 0003) — den Langtext nur
  aus dem Band der Spalte „Bezeichnung" lesen, sodass Maße (links) und Preise
  (rechts) gar nicht erst hineinkommen. Teilt die Tabellen-/Spaltenerkennung mit
  dem Bild-Crop (PRD 0002). Bevorzugter Zielzustand; wird als eigener Slice
  umgesetzt.
- **Zwischenstand: Regex-Bereinigung pro Template, Parse-Zeit** (ADR 0002) —
  funktioniert und ist für SCHUCHTER ausgeliefert. Kein gemeinsamer
  Export-Sanitizer.
- **Geteilte Helfer**, die jedes Template aufruft: führende Zahl-Tokens
  entfernen, B/H-Zeile normalisieren (heute in `template_schuchter` als
  `_strip_leading_numeric_tokens` / `_normalize_bh_line` — Kandidaten für
  `template_common`, damit andere Templates sie wiederverwenden).
- **Regeln** wie in ADR 0002: führend entfernen, Ende behalten, B/H normalisieren.
  Kurztext-Bereinigung folgt denselben Regeln, aber mit eigenem Muster
  (Maße hängen dort eher hinten — pro Anbieter zu bestätigen).
- **Re-Processing** bestehender Belege: ein Mechanismus/Lauf, der gespeicherte
  Dokumente neu parst (Umfang/Trigger im Issue zu klären).
- **Export-Vertrag bleibt eingefroren** — nur Textinhalt ändert sich, keine
  Spalten/Struktur (`tests/test_export_contract.py`).

## Testing Decisions

- Tests prüfen **beobachtbares Verhalten**: den bereinigten Text aus
  `build_vendoc_payload` bzw. der Template-Extraktion — nicht interne Helfer-Aufrufe.
- **Pro Anbieter** ein Property-Test über die lokalen Samples
  (`samples/pdfs/candidates/offers/<anbieter>/*.pdf`): kein Langtext-/Kurztext-
  Zeile beginnt mit einer nackten Zahl bzw. enthält Preis-/Koordinatenmüll.
- Prior Art: `tests/test_schuchter_longtext.py` (genau dieses Muster) und die
  wertbasierten Tests in `tests/test_vendoc_exporter.py`.
- Konkrete Leak-Zeilen aus Meldungen (Dragan) als Fixtures aufnehmen.

## Out of Scope

- Änderungen an der Export-Struktur/Spalten (eingefroren).
- VenDoc-seitige Verarbeitung der Texte.
- Anbieter, die keine zeichnungsbasierten Positionslayouts haben und nachweislich
  nicht leaken (erst per Property-Test bestätigen, dann ggf. überspringen).

## Further Notes

- SCHUCHTER ist umgesetzt (Kurz- **und** Langtext): führende Zahl-Tokens
  entfernt, B/H normalisiert, angehängte Maß-Paare (`965 1000`) und einzelne
  Flügelnummern (`DK-Rechts 1`) entfernt; mehrstellige Spezifikationen
  (`Aufdopplung 200`, `bis 110`, B/H-Höhe) bleiben. Live an #585 verifiziert.
  Nächste Anbieter offen (→ `/to-issues`).
- Rollout im Docker: Code ist als Volume gemountet → **kein Rebuild**, nur
  `docker compose -f infra/docker-compose.yml restart api`, danach betroffene
  Belege neu verarbeiten.
- Reihenfolge der Anbieter nach Häufigkeit/Meldungslage priorisieren
  (SCHUCHTER zuerst, da gemeldet).
