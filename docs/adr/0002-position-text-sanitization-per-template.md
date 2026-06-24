# Positionstexte werden pro Lieferanten-Template zur Parse-Zeit bereinigt

Kurz- und Langtexte einer Position (`description_short`, `description_long`)
dürfen keine Layout-Artefakte enthalten: Positions-/Flügelnummern,
Kopplungs-/Koordinatenzahlen, Referenzcodes oder Preise. Wir bereinigen diese
**pro Lieferanten-Template zur Parse-Zeit** (z. B. SCHUCHTER in
`api/template_schuchter.py`), nicht über einen gemeinsamen Sanitizer zur
Export-Zeit.

**Warum diese Wahl:** Pro Template lässt sich am sichersten zwischen Layout-Müll
und echter Beschreibung unterscheiden, weil die Filterregeln auf das jeweilige
Belegformat zugeschnitten sind. Ein gemeinsamer Export-Sanitizer würde leichter
echte Inhalte anderer Lieferanten beschädigen.

**Filterregeln (mit Lukas bestätigt, Stand SCHUCHTER):**
- führende reine Zahl-Tokens am Zeilenanfang entfernen (stoppt am ersten Token
  mit Buchstaben, daher bleiben `1-flg`, `2x`, `3xEsg`, `B/H:`, `+unten`);
- Endzahlen unangetastet lassen (oft echte mm-Maße);
- B/H-Zeilen auf das reine Maß `B/H: <Breite>x <Höhe>` normalisieren.

**Bewusste Konsequenz:** Da die Bereinigung beim Parsen greift, tragen
**bereits gespeicherte Dokumente** weiterhin den alten Text — sie müssen
**neu verarbeitet** werden, damit der saubere Text entsteht. Ein einmaliger
Re-Parse-Lauf über bestehende Belege ist daher Teil des Rollouts.

Siehe `CONTEXT.md` (Positionstext), das PRD
`docs/prds/0001-position-text-sanitization.md` und
`tests/test_schuchter_longtext.py`.
