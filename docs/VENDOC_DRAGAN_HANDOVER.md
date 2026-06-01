# VenDoc Handover fuer Dragan

Stand: 2026-05-28

## Zweck

Diese Datei ist die technische Uebergabe fuer Abstimmungen mit Dragan.

Sie dokumentiert:

- was in der App bereits umgesetzt ist
- welche Felder oder Tabellen im Zielsystem benoetigt werden
- wie sich der VenDoc-Export aktuell verhaelt

## Aktueller Stand

### 1. Export nach `SRTemp`

Der VenDoc-Export schreibt in:

- `dbo.vendoc_import_headers`
- `dbo.vendoc_import_positions`

Sobald ein Live-Export erfolgreich nach `SRTemp` geschrieben wurde, betrachten wir das Dokument in unserer App als bereits in VenDoc importiert.

### 2. Doppelimport-Warnung

Vor einem erneuten Live-Export prueft die UI, ob fuer das Dokument bereits ein erfolgreicher Live-Export existiert.

Technische Regel:

- Historie aus `vendoc_export_jobs`
- relevant ist mindestens ein Datensatz mit:
  - `document_id = aktuelles Dokument`
  - `dry_run = false`
  - `status = 'exported'`

UI-Verhalten:

- Es erscheint ein App-Modal statt eines Browser-Popups.
- Hinweistext:
  - Das Dokument wurde bereits importiert.
  - Ein erneuter Import ueberschreibt keinen bestehenden Beleg.
  - Es wird ein zusaetzlicher Beleg im ERP erzeugt.

### 3. Kundenauswahl

Bereits umgesetzt:

- Kundendropdown in der UI
- Kundenauswahl ist im Reiter `Start` sichtbar
- `customer_id` wird im Header mit exportiert

Die Kundenzuordnung muss damit nicht erst am Ende im Reiter `Freigabe` gesetzt werden.

### 4. Bezeichnungen / Kurztexte

Bereits umgesetzt:

- Preise werden aus `description_short` entfernt
- die eigentliche Bezeichnung bleibt erhalten
- Positionsfilter im Reiter `Positionen` ist klarer benannt:
  - statt `Nur Auffällige`
  - jetzt `Nur mit Fehlern/Warnungen`

### 5. Langtext / Gewichte / Bilder

Bereits umgesetzt:

- `description_long` bleibt als Plaintext erhalten
- Gewichtsangaben bleiben erhalten
- das kombinierte RTF-Feld mit Text + Bild bleibt erhalten:
  - `image_long_text_rtf`

Neu umgesetzt:

- zusaetzlich wird jetzt pro Position erzeugt:
  - `text_only_rtf` -> nur Text
  - `image_only_rtf` -> nur Bild

Wichtig:

- `image_long_text_rtf` bleibt unveraendert erhalten
- die zwei neuen Felder kommen nur zusaetzlich dazu

### 6. Benutzer und Nachvollziehbarkeit

Neu umgesetzt:

- eine gemeinsame App-Instanz fuer alle Mitarbeiter
- echtes Login pro Mitarbeiter
- keine Rollen/Rechteverwaltung
- alle angemeldeten Benutzer koennen alles bedienen
- Freigaben und manuelle Aenderungen werden mit Benutzername und IP protokolliert

Warum so:

- mehrere Mitarbeiter koennen gleichzeitig arbeiten
- keine getrennten Ports oder getrennten Instanzen noetig
- trotzdem ist nachvollziehbar, wer freigegeben oder manuell eingegriffen hat

Aktuell protokollierte Aktionen:

- Login / Logout
- Upload
- Verarbeitung gestartet / abgeschlossen / fehlgeschlagen
- manuelle Bildzuordnung
- manuelle PDF-Crops
- Bildzuordnung entfernen
- Position als geprueft markieren / zuruecksetzen
- Dokument freigeben / Freigabe zuruecksetzen
- Kunde in SRTemp setzen
- VenDoc Dry-Run
- VenDoc Live-Export erfolgreich / fehlgeschlagen
- Verarbeitung zuruecksetzen

Neue Tabellen in unserer App-Datenbank:

- `app_users`
- `app_sessions`
- `audit_events`

Wichtige Environment-Variablen:

- `APP_AUTH_ENABLED`
  - Default: inaktiv
  - fuer den Server auf `true` setzen

- `APP_BOOTSTRAP_USERNAME`
  - initialer Benutzer beim ersten Start

- `APP_BOOTSTRAP_PASSWORD`
  - Passwort fuer den initialen Benutzer

- `APP_BOOTSTRAP_DISPLAY_NAME`
  - Anzeigename fuer den initialen Benutzer
  - optional; wenn leer, wird der Benutzername angezeigt

- `APP_SESSION_TTL_HOURS`
  - Gueltigkeit einer Login-Session
  - Default: 12 Stunden

Benutzeranlage:

- der Bootstrap-Benutzer wird ueber ENV beim Start angelegt, wenn er noch nicht existiert
- wenn der Benutzer bereits existiert, wird sein Passwort nicht automatisch durch ENV ueberschrieben
- wenn noch kein Benutzer existiert, kann der erste Benutzer direkt im Login-Dialog angelegt werden
- weitere Benutzer koennen angemeldete Benutzer im Admin-Bereich der UI anlegen
- technisch ist dafuer weiter die API `POST /auth/users` vorhanden
- Rollen sind bewusst nicht vorgesehen
- die UI fragt fuer neue Benutzer nur Benutzername und Passwort ab; ein Anzeigename ist technisch optional, aber fuer die Bedienung nicht notwendig

### 7. Alternative Positionen

Neu umgesetzt:

- pro Dokument gibt es eine Einstellung fuer die Behandlung von Alternativpositionen
- die Einstellung ist im Reiter `Start` sichtbar
- die Einstellung wird in unserer App-Datenbank gespeichert:
  - `documents.alternative_position_mode`

Moegliche Werte:

- `nested`
  - Alternativen werden direkt unter der Hauptposition nummeriert
  - Hauptpositionen werden im Export lueckenlos neu nummeriert
  - Beispiel:
    - Position `1`
    - Alternative `1.1`
    - Alternative `1.2`
    - naechste Hauptposition `2`

- `append`
  - Alternativen werden am Ende der Positionsliste angehaengt
  - normale Positionen und Alternativen werden im Export lueckenlos neu nummeriert
  - Beispiel:
    - bei 7 normalen Positionen werden Alternativen als `8`, `9`, ... exportiert

Technisches Verhalten im Export:

- Positionsnummern fuer `SRTemp` sind immer lueckenlos
- jede Alternative bekommt `is_alternative = true`
- bereits als Alternative erkannte Positionen werden entsprechend umnummeriert
- zusaetzlich werden eingebettete Langtextzeilen mit Prefix `Alternativ:` als eigene Alternativpositionen exportiert
- diese eingebetteten Alternativzeilen werden aus dem Langtext der Hauptposition entfernt, damit sie nicht doppelt vorkommen
- wenn in einer Alternativzeile ein `EP:`-Preis steht, wird dieser als `unit_price` uebernommen
- hat die Alternativzeile keinen eigenen Preis, bleibt `unit_price` leer

UI-Verhalten:

- im Reiter `Positionen` wird pro Zeile neben der extrahierten Originalposition auch die geplante Export-Position angezeigt
- der Kopfbereich zeigt, welcher Alternativmodus aktiv ist
- eingebettete `Alternativ:`-Zeilen erscheinen als eigene Positionen erst in SQL-Vorschau, Dry-Run oder Live-Export

## Welche Felder Dragan im Zielschema anlegen soll

### Empfohlen in `dbo.vendoc_import_positions`

Bitte zwei neue Spalten anlegen:

- `text_only_rtf`
- `image_only_rtf`

Empfohlener Typ:

- `nvarchar(max)` fuer beide Spalten

### Fachliche Bedeutung

- `text_only_rtf`
  - enthaelt den bisherigen Positions-Langtext als RTF, aber ohne Bild

- `image_only_rtf`
  - enthaelt nur das Bild als RTF
  - ohne den restlichen Text

### Bestehendes Feld bleibt

Das bestehende Feld bleibt weiter in Verwendung:

- `image_long_text_rtf`

Dieses Feld enthaelt weiterhin:

- Text + Bild kombiniert

## Technische Kompatibilitaet

Die App ist bereits so gebaut, dass die neuen Felder optional sind.

Das heisst:

- wenn die Spalten im MSSQL-Schema vorhanden sind:
  - werden sie automatisch mitgeschrieben
- wenn die Spalten noch nicht vorhanden sind:
  - laeuft der Export weiter wie bisher
  - es bricht nichts

## Unterstuetzte Spaltennamen

Falls Dragan andere Namen bevorzugt, sind aktuell zusaetzlich diese Aliasse unterstuetzt:

- fuer Text-RTF:
  - `text_only_rtf`
  - alternativ `text_rtf`

- fuer Bild-RTF:
  - `image_only_rtf`
  - alternativ `image_rtf`
  - alternativ `img_rtf`

Empfehlung trotzdem:

- im SQL-Schema direkt die finalen Namen verwenden:
  - `text_only_rtf`
  - `image_only_rtf`

## Was wir in der App bereits gemacht haben

Umgesetzt:

- VenDoc-Importwarnung fuer bereits exportierte/importierte Dokumente
- App-styled Confirm-Modal fuer Live-Import
- App-styled Login-Dialog
- Benutzeranzeige mit Logout in der Kopfzeile
- Audit-Log fuer Freigaben und manuelle Eingriffe
- Kundenauswahl im Reiter `Start`
- `customer_id` im Header
- bereinigte `description_short`
- Erhalt der Gewichtsangaben im Langtext
- RTF mit kombiniertem Text + Bild
- zusaetzliches Text-RTF
- zusaetzliches Bild-RTF
- Schalter fuer Alternativpositionen im Reiter `Positionen`
- Exportmodus fuer Alternativen:
  - direkt unter Hauptposition
  - oder gesammelt am Ende der Positionsliste
- lueckenlose Exportnummerierung fuer beide Alternativmodi
- Hinweis und Exportpositionsanzeige im Reiter `Positionen`
- Sammelpositionen fuer gleiche Alternativen im Modus `Am Ende anhaengen`
- sichtbarer angemeldeter Benutzer und `Abmelden` in der Kopfzeile
- vereinfachte Benutzeranlage nur mit Benutzername und Passwort
- Canary kann bei aktivierter Auth automatisch mit `.env`- oder `PDR_CANARY_*`-Credentials laufen
- Provider-/Validierungsregression aktuell gruen: `209 passed, 2 warnings`
- Dry-Run fuer Muigg/SRTemp fachlich geprueft: `customer_id` im Header, bereinigte Kurztexte, Gewichte im Langtext und RTF-Bildeinbettung bleiben erhalten

## Was Dragan aktuell pruefen soll

1. Ob `dbo.vendoc_import_positions` die zwei neuen Spalten bekommen soll:
   - `text_only_rtf`
   - `image_only_rtf`

2. Ob VenDoc intern:
   - das kombinierte Feld braucht
   - oder Text und Bild getrennt weiterverarbeitet werden sollen

3. Ob die empfohlenen Spaltennamen fuer ihn passen

4. Ob die Audit-Informationen fuer ihn ausreichend sind:
   - Benutzer
   - IP
   - Aktion
   - Dokument / Position
   - Details als JSON

5. Ob die Positionsnummerierung und Gruppierung fuer Alternativen in VenDoc so passt:
   - `1.1`, `1.2` direkt unter der Hauptposition
   - oder gesammelt am Ende, z.B. alle gleichen `Holzart: Fichte ...` als eine gemeinsame Alternativposition

## Kurzfassung fuer Mail / Teams

Folgender Text kann an Dragan geschickt werden:

> Wir lassen das bestehende kombinierte Feld `image_long_text_rtf` unveraendert bestehen.
> Zusaetzlich erzeugen wir jetzt pro Position zwei weitere RTF-Felder:
> `text_only_rtf` fuer den reinen Text und `image_only_rtf` fuer das Bild separat.
> Wenn du diese Werte direkt in `SRTemp` haben willst, brauchen wir in `dbo.vendoc_import_positions` zwei neue Spalten vom Typ `nvarchar(max)` mit genau diesen Namen.
> Alternativ koennen wir auch `text_rtf` sowie `image_rtf` / `img_rtf` bedienen, falls du andere Feldnamen bevorzugst.

Zum Mehrbenutzerbetrieb:

> Wir betreiben eine gemeinsame App-Instanz fuer alle Mitarbeiter. Jeder bekommt einen eigenen Login, aber ohne Rollenmodell, weil alle alles koennen sollen. Freigaben und manuelle Aenderungen werden in unserer App-Datenbank im Audit-Log mit Benutzer, IP, Aktion, Dokument/Position und Details protokolliert.

Zu Alternativpositionen:

> Im Reiter `Positionen` gibt es jetzt eine Einstellung fuer Alternativpositionen. Wir koennen Alternativen entweder direkt unter der Hauptposition exportieren, z.B. `1.1` und `1.2`, oder am Ende der Positionsliste ausgeben.
> Wenn `Am Ende anhaengen` gewaehlt ist, fassen wir gleiche Alternativen zu Sammelpositionen zusammen. Beispiel: Wenn unter mehreren Fensterpositionen jeweils `Alternativ: Holzart: Fichte ...` steht, entsteht am Ende eine gemeinsame Alternativposition `Holzart: Fichte ...` mit aufsummierter Menge und entsprechend berechnetem Einzelpreis. In beiden Modi setzen wir bei diesen Positionen `is_alternative = true`.
> Die Positionsnummern fuer den Export werden lueckenlos neu vergeben. Im Reiter `Positionen` zeigen wir die geplante Exportposition, Originalpositionen und Hinweise wie `neu nummeriert` direkt an.
