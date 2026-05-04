# UI/UX Redesign

Stand: 2026-04-27

## Ziel

Die Anwendung soll wie ein modernes, gefuehrtes Pruefprodukt wirken: ruhig, schnell, klar und ohne sichtbare technische Altlasten. Der Nutzer soll jederzeit wissen:

- Welches Dokument ist aktiv?
- Ist das Dokument freigabefaehig?
- Was ist der naechste sinnvolle Schritt?
- Welche Positionen oder Bilder brauchen Aufmerksamkeit?

## Leitprinzipien

- Eine primaere Aktion pro Zustand.
- Upload startet automatisch die Verarbeitung.
- Technische Diagnose, JSON, Parser-Vergleiche und Debug bleiben ausserhalb des Hauptflows.
- Der Hauptflow ist `Start -> Positionen -> Bilder -> Freigabe`.
- PDF und Review sind gleichwertige Arbeitsbereiche: links Referenz, rechts Entscheidung.
- Tabellen werden nur genutzt, wenn sie schneller pruefbar sind; Details bleiben einklappbar.
- Visuelle Hierarchie: grosse ruhige Flaechen, wenige Linien, klare Statusfarben, weiche Tiefe.

## Operator Flow

1. Dokument auswaehlen oder PDF ablegen.
2. Verarbeitung startet automatisch.
3. Start-Screen zeigt Gesamtstatus, Pflichtfelder, Summen und offene Punkte.
4. Positionen-Screen zeigt nur pruefrelevante Zeilen zuerst.
5. Bilder-Screen fokussiert fehlende und konfliktbehaftete Bildzuordnungen.
6. Freigabe-Screen sammelt Abschlusscheck, Pruefer und Notiz.
7. Erst danach darf VenDoc exportiert werden.

## UI-Zielbild

### Shell

- Oben eine kompakte Command-Bar mit Dokumentauswahl, PDF-Upload, Status und einer primaeren Aktion.
- Kein grosser Marketing-Header im Arbeitsmodus.
- Diagnose/Export nur als Sekundaermenue.

### Review

- Stepper mit vier Kapiteln: Start, Positionen, Bilder, Freigabe.
- Eine Guide-Bar erklaert je Kapitel den naechsten Schritt.
- Start zeigt Entscheidung statt Datenwuste.
- Freigabe ist ein Abschluss-Screen, nicht nur ein Formular.

### Visuelles System

- Heller Hintergrund, sehr dezente Tiefe.
- Apple-aehnliche Typografie ueber System Fonts.
- SR-Rot nur fuer Fokus, Warnung und primaere Aktion.
- Keine Rasterhintergruende, keine dunklen Admin-Flaechen, keine Button-Wolken.

## Umsetzung in Etappen

### Task 1: Zielbild dokumentieren

Status: erledigt

### Task 2: Neue App-Shell

Status: erledigt

Umfang:

- Neue `v3`-Shell-Klassen fuer sichtbare Struktur.
- Bestehende IDs bleiben fuer JS-Funktionalitaet.
- Alt-CSS wird schrittweise abgeloest, nicht weiter ausgebaut.
- Header-Collapse ist deaktiviert; die Command-Bar bleibt stabil.
- Schauraum-Branding ist als kleines Logo in der Command-Bar sichtbar, ohne den Arbeitsmodus zu dominieren.

### Task 3: Guided Review

Status: in Arbeit

Umfang:

- Start-Screen als Entscheidungsseite neu komponieren. Status: erster V3-Stand umgesetzt, Statusfarben auf Akzente reduziert.
- Positionen als Review-Liste optimieren. Status: erster V3-Stand als Card-Tabelle umgesetzt.
- Bilder nach Position und Konfliktstatus gruppieren. Status: erster V3-Stand mit Bildpruefkopf und priorisierter Galerie umgesetzt.
- Freigabe als Abschluss-Check. Status: erster V3-Stand mit Abschlusslayout und Aufgabenliste umgesetzt.
- Stepper/Tab-Leiste im Review-Header stabilisiert. Status: feste, helle Header-Navigation statt schwebender/transparenter Tabs.
- PDF-Vorschau visuell integriert. Status: Browser-PDF-Toolbar wird ausgeblendet, eigene dunkle App-Controls fuer Seite, Zoom, Fit, Download und externes Oeffnen sind umgesetzt.

### Task 4: CSS-Bereinigung

Status: in Arbeit

Umfang:

- Alte PoC-Designschichten entfernen. Status: ungenutzte `app-v2`-Schicht, alte Header-Collapse-Logik und V3-Collapse-Selektoren entfernt.
- Finale Tokens und Komponenten konsolidieren.
- Responsive- und Accessibility-Zustaende pruefen.

## V3 Design Reset

Status: beschlossen am 2026-04-27

Die aktuelle v2-Shell verbessert die alte UI, ist aber noch kein echter Produkt-Reset. V3 wird nicht auf den vorhandenen Header/Kachel-Patterns aufbauen, sondern die sichtbare App neu komponieren.

### Grundentscheidung

- Kein Marketing-Header im Arbeitsmodus.
- Kein starkes Collapse-on-scroll.
- Keine Dashboard-Kachelwüste auf der Startseite.
- Keine technischen Diagnoseaktionen im sichtbaren Hauptflow.
- Keine mehrfachen Navigationskonzepte.
- Keine Raster-, Admin- oder Enterprise-Optik.

### Scroll- und Collapse-Verhalten

Die aktuelle Idee eines einklappenden Headers wird verworfen.

Begruendung:

- Der Nutzer arbeitet mit PDF und Review gleichzeitig; ein wechselnder Header stoert die Orientierung.
- Collapse erzeugt zwei UI-Zustaende, die beide sauber gestaltet und getestet werden muessten.
- Eine kompakte, immer stabile Command-Bar ist fuer diesen Workflow besser.

V3-Verhalten:

- Oben bleibt eine sehr schlanke, sticky Command-Bar.
- Beim Scrollen wird sie nicht neu layoutet, sondern bleibt gleich hoch.
- Nur optionale Detailbereiche innerhalb des Review-Panels duerfen einklappen.
- PDF und Review scrollen unabhaengig voneinander.
- Der aktive Workflow-Schritt bleibt im Review-Panel sticky.

### Neue Informationsarchitektur

#### Ebene 1: Command-Bar

Sichtbar:

- Produktmarke kurz: `SR Import`
- Dokument-Picker
- kleiner Dokumentstatus
- PDF-Auswahl
- primaere Aktion je Zustand:
  - `Verarbeiten`
  - `Pruefung fortsetzen`
  - `Freigeben`
  - `Export vorbereiten`

Nicht sichtbar im Hauptflow:

- JSON
- Parser-Diagnose
- Debug
- Reset
- interne Run-States

Diese Funktionen wandern in ein Admin-Menue.

#### Ebene 2: Workbench

Layout:

- Links: PDF-Viewer als ruhiger Referenzbereich.
- Rechts: Review-Workbench als gefuehrte Aufgabe.
- Optional spaeter: flexible Split-Breite.

#### Ebene 3: Review Flow

Schritte:

1. `Start`
2. `Positionen`
3. `Bilder`
4. `Freigabe`

Jeder Schritt hat:

- Titel
- 1 Satz Ziel
- naechste Aktion
- kurze Statuszeile
- nur relevante Inhalte

### Screen-Konzept

#### Start

Ziel:

- In 5 Sekunden entscheiden, ob das Dokument direkt freigabefaehig ist oder wo gearbeitet werden muss.

Sichtbar:

- Grosser Status: `Freigabe moeglich` oder `Pruefung erforderlich`.
- Kurzfassung: Positionen, Bilder, offene Punkte.
- Drei Checks:
  - Pflichtfelder
  - Summen
  - Bildabdeckung
- Button/Link zur naechsten offenen Stelle.

Nicht sichtbar:

- Rohdaten-Kacheln wie Dokument-ID, Status, Dokumenttyp, Projekt.
- Lange Betragszeilen.
- Quellenlage.

Diese Daten kommen in `Details`.

#### Positionen

Ziel:

- Schnell erkennen, welche Positionen geprueft werden muessen.

Sichtbar:

- Filter `Nur offene`.
- Review-Liste statt schwerer Tabelle.
- Pro Position: Nummer, Kurztext, Menge, Betrag, Bildthumbnail, Status.
- Klick oeffnet Details mit Langtext, Preisen, Kandidaten und Pruefhinweisen.

#### Bilder

Ziel:

- Bildzuordnungen als USP der App sichtbar und sicher pruefbar machen.

Sichtbar:

- Gruppen:
  - Fehlend
  - Konflikte
  - Eindeutig
- Bildkarten nach Position, nicht nur globale Galerie.
- Direktaktion: `Als final setzen`.

#### Freigabe

Ziel:

- Abschluss ohne Unsicherheit.

Sichtbar:

- Abschlussstatus.
- Blocker oder Gruenes Licht.
- Pruefer.
- Notiz.
- Primaerbutton `Dokument freigeben`.
- Danach spaeter `VenDoc Export vorbereiten`.

### Visuelles System V3

- Hintergrund: `#f5f5f7` / sehr hell.
- Panels: weiss, maximal dezenter Blur, keine starken Schatten.
- Radius: 18-28px konsistent, nicht jede Unterkomponente maximal rund.
- Typografie: Systemfont, grosse Titel, kleine ruhige Metatexte.
- Farbe: SR-Rot nur fuer Fokus/Primaeraktion; Gruen/Warnung nur als Status.
- Kein Pattern-/Grid-Hintergrund.
- Keine dicken Pill-Badges als Standard.
- Weniger Borders, mehr Raum und klare Gruppen.

### Umsetzungsschritte V3

1. Neues HTML-Geruest fuer Shell und Workbench anlegen.
2. Alte sichtbare Header-Struktur ausblenden oder ersetzen.
3. CSS in eine klare V3-Sektion konsolidieren.
4. Start-Screen neu bauen.
5. Positionen-Screen neu bauen.
6. Bilder-Screen neu bauen.
7. Freigabe-Screen neu bauen.
8. Danach alte CSS-Schichten entfernen.

### Akzeptanzkriterien

- Der erste Screen wirkt nicht mehr wie eine Admin- oder Dashboard-App.
- Es gibt keine Header-Sprunglogik beim Scrollen.
- Ein neuer Mitarbeiter erkennt ohne Erklaerung den naechsten Schritt.
- Technische Funktionen sind erreichbar, aber nicht dominant.
- Review-Fokus liegt auf Positionen und Bildern, nicht auf Rohdaten.
