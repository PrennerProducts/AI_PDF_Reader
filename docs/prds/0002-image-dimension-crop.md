# PRD 0002 — Positionsbilder: optimalen Bildbereich je Bild erkennen (Bemaßung nicht abschneiden)

Verwandt: CONTEXT.md, `api/extractor.py` (Crop-Logik), PRD
`docs/prds/0001-position-text-sanitization.md` (anderer SCHUCHTER-Befund von Dragan).

## Problem Statement

Bei SCHUCHTER (und potenziell anderen Anbietern) werden bei den
Positionsbildern (den Zeichnungen) **teilweise die rechten Bemaßungen
abgeschnitten** — sie gehören aber aufs Bild. Beispiel: Doc #585, Pos 9
(Bild #16569, Seite 4): die rechte Höhen-/Maßangabe fehlt im zugeordneten Bild.

Ursache (Diagnose): Der Bildausschnitt für die Positionszeichnung wird über
**feste Konstanten** bestimmt, u. a. eine harte rechte Grenze
`POSITION_LINE_ART_RIGHT_PT = 220.0` und feste Streifen-Ratios
(`LEFT_SKETCH_STRIP_RIGHT_RATIO = 0.34` …). Liegt die rechte Bemaßung jenseits
dieser festen Grenze, wird sie weggeschnitten. Der Ausschnitt ist also nicht an
den tatsächlichen Inhalt des jeweiligen Bildes angepasst.

## Solution

Statt fester Crop-Grenzen den **tatsächlichen Umfang jedes Bildes inhaltsbasiert
erkennen** und immer den **optimalen Bildbereich** wählen — die komplette
Zeichnung inklusive aller (auch rechter) Bemaßungen, ohne Fremdinhalt
benachbarter Positionen/Spalten. Konkret: aus dem gerenderten Inhalt die
echte Bounding-Box der Zeichnung bestimmen (das Projekt hat dafür bereits
`_component_bboxes()`), mit kontrolliertem Rand und Schutzgrenzen.

**Rechte Grenze über das Tabellenlayout (Kernidee).** Die Belege sind Tabellen
mit Kopf `Pos. | Menge EH | Bezeichnung | Einzelpreis | Gesamtpreis`. Die
Zeichnung steht links (Pos./Menge-Bereich); rechts davon beginnt die Spalte
**Bezeichnung** (der Langtext). Die rechte Crop-Grenze ist daher der **linke
Spaltenrand von „Bezeichnung"** — bis dorthin darf das Bild maximal gehen, nicht
weiter. Diese Grenze wird pro Beleg aus der Kopfzeile erkannt (x-Position des
Worts „Bezeichnung"), statt über die feste Konstante `POSITION_LINE_ART_RIGHT_PT`.
So sind die rechten Bemaßungen enthalten (sie liegen links von „Bezeichnung"),
aber der Langtext läuft nicht ins Bild.

## User Stories

1. Als VenDoc-Importeur möchte ich auf jedem Positionsbild die vollständige
   Zeichnung inkl. aller Bemaßungen, damit im ERP nichts Wichtiges fehlt.
2. Als Bearbeiter möchte ich, dass der Bildausschnitt sich an den realen Inhalt
   anpasst (nicht an feste Punkte/Ratios), damit unterschiedlich breite
   Zeichnungen jeweils optimal erfasst werden.
3. Als Bearbeiter möchte ich, dass der Ausschnitt **nicht** in die Nachbar-
   position oder die Textspalte rechts überläuft, damit kein Fremdinhalt
   hineinkommt.
4. Als Entwickler möchte ich erkennen können, wenn ein Bild rechts (oder an
   einer Kante) abgeschnitten ist, damit Clipping automatisch auffällt.
5. Als Bearbeiter anderer Anbieter möchte ich, dass die Umstellung deren Bilder
   nicht verschlechtert (geteilte Crop-Logik), damit nichts regressiert.

## Implementation Decisions

- **Inhaltsbasierte Bounding-Box statt fester Grenzen.** Die rechte (und ggf.
  obere/untere) Crop-Grenze aus dem tatsächlichen Inhalt ableiten
  (Non-White-/Komponenten-Maske, vorhandenes `_component_bboxes()`), statt
  `POSITION_LINE_ART_RIGHT_PT` / Streifen-Ratios als harte Grenze zu verwenden.
- **Rechte Schutzgrenze = Spaltenrand „Bezeichnung".** Pro Beleg aus der
  Tabellen-Kopfzeile die x-Position der Spalte „Bezeichnung" bestimmen und als
  rechte Obergrenze des Bildausschnitts verwenden. Die inhaltsbasierte
  Bounding-Box darf bis dorthin, aber nicht darüber. Fallback auf eine Konstante
  nur, wenn die Kopfzeile nicht erkannt wird.
- **Weitere Schutzgrenzen (Guard Rails).** Oben/unten an die Position begrenzen
  (nächste Position / Separator), damit der Bereich nicht in Nachbarinhalte
  ausufert. Die bisherigen Konstanten werden zu Ober-/Untergrenzen bzw. Padding,
  nicht zur fixen Schnittkante.
- **Geteilte Logik in `api/extractor.py`** → Änderung betrifft **alle**
  Anbieter. Daher anbieterübergreifend gegenprüfen, nicht nur SCHUCHTER.
- **Diagnose zuerst.** Vor der Umstellung an realen Belegen reproduzieren, wo und
  warum die feste Grenze greift (z. B. Pos 9 / #16569), und die neue
  Bounding-Box dagegen messen.

## Testing Decisions

- **Visuell/manuell** im UI prüfen (Pixel/Bildausschnitt lassen sich schwer als
  klassischer Unit-Test fassen): zugeordnete Bilder vor/nach an betroffenen
  Positionen (Start: #585 Pos 9) ansehen.
- **Clipping-Metrik als automatischer Wächter:** prüfen, dass am rechten (und
  anderen) Bildrand innerhalb von N Punkten **kein** zusammenhängender
  Non-White-Inhalt mehr liegt (sonst wurde wahrscheinlich abgeschnitten). Als
  Property-Test über Sample-Belege je Anbieter.
- **Regression je Anbieter:** Crop-Breite/-Höhe deckt die Inhalts-Bounding-Box
  ab; Ausschnitt überschreitet nicht die Guard-Rails.
- Prior Art: `_component_bboxes()` und die Layout-Metadaten in `extractor.py`.

## Out of Scope

- Textbereinigung (siehe PRD 0001).
- Bilder, die keine Positionszeichnungen sind (Logos/Header werden separat
  gefiltert).
- Änderungen am Export-Vertrag/Schema (eingefroren).

## Further Notes

- Konkreter Startfall: Doc #585, Pos 9, Bild #16569, Seite 4 (rechte Bemaßung
  fehlt).
- Risiko geteilter Code: Die feste Grenze existiert vermutlich, um Überlauf in
  die Textspalte zu verhindern — die Guard Rails müssen diesen Schutz erhalten.
- Rollout wie bei PRD 0001: Docker-Restart (kein Rebuild), betroffene Belege neu
  verarbeiten, damit neue Bildausschnitte entstehen.
