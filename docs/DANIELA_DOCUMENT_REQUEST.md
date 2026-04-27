# Dokumentenbedarf fuer Parser und VenDoc

Stand: 2026-04-27

Diese Liste ist die konkrete Anforderung an Daniela fuer weitere Test- und Parserdokumente.

## Aktueller Befund

Der Angebotsparser ist fuer den aktuellen Korpus gruen:

- 39 Angebots-PDFs.
- 11 Anbieter-Templates.
- 21 gruene Kandidaten.
- 18 kanonische Regression-PDFs.

Es gibt aktuell keinen akuten Blocker bei normalen Angebots-PDFs. Die relevanten Luecken fuer Produktionsreife liegen bei vollstaendigen Projektpaketen, Auftragsbestaetigungen, technischen Beilagen, Bildzuordnung und weiteren Layoutvarianten.

## Was wir von Daniela brauchen

### Prioritaet 1 - Komplette Projektpakete

Bitte pro Anbieter, wenn verfuegbar, 1 bis 2 komplette reale Projektpakete schicken.

Ein Paket besteht idealerweise aus:

- Angebot.
- Auftragsbestaetigung, falls vorhanden.
- Technische Detailansichten, Elementuebersichten, Schnitte oder Grafik-PDFs.
- Separate Bild-/Visualisierungsdateien, falls diese beim Lieferanten separat mitkommen.
- Alle Dokumente sollen zu demselben Projekt bzw. derselben Lieferanten-Referenz gehoeren.

Warum:

- Damit pruefen wir nicht nur den Parser, sondern auch Bildzuordnung, Plausibilitaet und spaeter den VenDoc-Export.
- Einzelne isolierte PDFs helfen weniger als zusammenhaengende Projektpakete.

### Prioritaet 2 - Noch schwach abgedeckte Anbieter

Bitte zuerst Dokumente fuer diese Anbieter liefern, wenn weitere Varianten existieren:

- `sr_schauraum`: aktuell nur 1 Angebots-PDF, keine AB.
- `schachermayer`: aktuell nur 2 Angebots-PDFs und 1 AB; weitere echte Offerte/AB waeren wertvoll.
- `rekord_vomp`: Angebote sind gruen, aber ABs werden aktuell noch generisch erkannt; weitere AB-/Auftragsbeispiele waeren wichtig, falls ABs importiert werden sollen.
- `alu_one`: Angebote sind gruen, aber weitere komplette Pakete mit Grafik-/Schnittbeilagen helfen fuer Bild-/VenDoc-Tests.
- `entholzer`: Angebote sind gruen, aber weitere AB-/Bildbeispiele helfen fuer den Canary-Bildworkflow.

### Prioritaet 3 - Schwierige Layoutvarianten

Bitte gezielt Dokumente mit diesen Eigenschaften sammeln:

- Mehrseitige Angebote mit vielen Positionen.
- Angebote mit Alternativpositionen, Varianten oder Optionen.
- Angebote mit Rabattblöcken, Zwischensummen oder Nachlaessen.
- Angebote mit 0,00-Positionen oder Positionen ohne Preis.
- Positionen mit Unterpositionen, zum Beispiel `001.1`, `1a`, `av01.1`.
- Kopplungs-/Gruppenelemente, bei denen Teilpositionen und Hauptposition getrennt dargestellt sind.
- Dokumente mit separaten Bildern, Detailzeichnungen oder Elementuebersichten.

### Prioritaet 4 - Negative Beispiele

Bitte auch ein paar Nicht-Angebote schicken, damit der Import nicht falsche Dokumente als Angebote verarbeitet:

- Auftragsbestaetigungen.
- Rechnungen.
- Lieferscheine.
- reine Detailzeichnungen/Schnitte.
- Leistungserklaerungen.
- technische Produktdatenblaetter.

Diese Dateien sollen klar als Nicht-Angebote markiert werden.

## Naming und Upload

Wenn moeglich bitte Dateinamen nach diesem Schema verwenden:

```text
<anbieter>__angebot__<nummer>.pdf
<anbieter>__auftragsbestaetigung__<nummer>.pdf
<anbieter>__detailansicht__<projekt_oder_nummer>.pdf
<anbieter>__rechnung__<nummer>.pdf
<anbieter>__lieferschein__<nummer>.pdf
```

Beispiele:

```text
schuchter__angebot__A260396.pdf
muigg__auftragsbestaetigung__1250439.pdf
sr_schauraum__detailansicht__525073.pdf
```

Wenn das Umbenennen zu aufwendig ist, reicht auch eine kurze Liste daneben:

```text
Originaldatei.pdf -> Anbieter, Dokumenttyp, Projektreferenz, gehoert zu Paket X
```

Upload-Ziel im Repo:

```text
samples/pdfs/inbox/raw_company_tree/
```

Danach werden die Dateien sauber in Kandidaten, Regression oder Nicht-Angebote einsortiert.

## Konkrete Nachricht an Daniela

Hallo Daniela,

ich habe den aktuellen PDF-Korpus eingearbeitet. Die normalen Angebotsparser laufen derzeit stabil. Was uns fuer die naechste Ausbaustufe noch wirklich hilft, sind nicht einfach beliebige Einzel-PDFs, sondern komplette Beispielpakete pro Projekt.

Kannst du mir bitte, wenn vorhanden, pro Anbieter 1 bis 2 zusammenhaengende Projektpakete schicken? Ideal waere jeweils:

- Angebot
- Auftragsbestaetigung, falls vorhanden
- Detailzeichnungen, Elementuebersichten, Schnitte oder Grafik-PDFs
- separate Bilder/Visualisierungen, falls diese beim Lieferanten separat mitkommen

Besonders wertvoll waeren aktuell weitere Beispiele fuer SR-Schauraum, Schachermayer, Rekord Vomp, alu-one und Entholzer. Bei Rekord Vomp interessieren mich vor allem Auftragsbestaetigungen/Auftragsdokumente, falls diese spaeter auch importiert werden sollen.

Bitte auch schwierige Varianten mitschicken, falls du welche hast: Alternativpositionen, Rabattbloecke, 0-Euro-Positionen, Unterpositionen, Gruppenelemente oder Angebote mit separaten Bild-/Detailbeilagen.

Beim Dateinamen waere dieses Schema ideal:

```text
anbieter__angebot__nummer.pdf
anbieter__auftragsbestaetigung__nummer.pdf
anbieter__detailansicht__projekt-oder-nummer.pdf
```

Wenn Umbenennen zu viel Aufwand ist, passt auch eine kurze Liste mit Anbieter, Dokumenttyp und Projektreferenz je Datei.

Danke dir.
