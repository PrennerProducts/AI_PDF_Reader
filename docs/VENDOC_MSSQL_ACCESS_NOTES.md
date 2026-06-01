# VenDoc MSSQL Import: Zugriff, Mapping, Call-Notizen

Stand: 2026-05-28

## Zielbild

Die Anwendung laeuft auf einem Ubuntu-Server und verarbeitet Angebots-PDFs serverseitig.

Interne App-Datenbank:

- Postgres bleibt die fuehrende interne Datenbank fuer Uploads, Processing, Review, Freigabe, Logs und Export-Journal.

Externe VenDoc-Importdatenbank:

- Microsoft SQL Server.
- Datenbank: `SRTemp`.
- Tabellen:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`

Der VenDoc-Export wird als zusaetzlicher MSSQL-Writer umgesetzt. Er ersetzt nicht die interne Postgres-Persistenz.

## Aktueller Stand von Dragan

Mail-Zusammenfassung:

- CIBEX richtet den SQL-Zugriff ein.
- CIBEX soll sich direkt wegen der Verbindung melden.
- Dragan hat ein Ticket angelegt.
- Datenbank ist `SRTemp`.
- Es gibt zwei Tabellen: Kopf und Positionen.
- Einige Datenspalten sind anders oder nicht vorhanden; Details werden besprochen, sobald Zugriff moeglich ist.
- Dragan bereitet einen Datensatz mit Bildern vor.

Screenshot-Stand:

- SQL Server: `SVWAPP01\DREI`.
- Datenbank: `SRTemp`.
- Tabellen vorhanden:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`

## So erklaere ich es CIBEX

Kurzfassung:

> Unsere Anwendung laeuft auf einem Ubuntu-Server und soll serverseitig direkt auf eure Microsoft-SQL-Datenbank zugreifen.
> Wir schreiben die Importdaten automatisiert in die beiden vorbereiteten Tabellen in `SRTemp`.
> Dafuer brauche ich von euch die SQL-Server-Verbindungsdaten und die Netzwerkfreigabe fuer unseren Server.

Wenn Rueckfragen kommen:

> Ich brauche keine Browserfreigabe und keinen Remote-Desktop.
> Die Anwendung verbindet sich direkt vom Server auf euren SQL Server, wie jede normale externe Anwendung mit einer SQL-Datenbank.

Wenn nach der Technik gefragt wird:

> Die Anwendung ist in Python umgesetzt und greift serverseitig auf SQL Server zu.
> Auf unserer Seite verwenden wir einen SQL-Server-kompatiblen Python-Client bzw. den Microsoft SQL Server ODBC-Treiber.
> Auf eurer Seite brauche ich nur einen normalen SQL-Zugang auf die Datenbank.

## Was ich von CIBEX brauche

Technischer Zugriff:

- SQL-Server Hostname oder IP.
- Instanzname, falls relevant.
- TCP-Port, ideal fix.
- Datenbankname `SRTemp`.
- SQL-Benutzer.
- Passwort.
- Firewall-Freigabe fuer die IP des Ubuntu-Servers.
- Info, ob TLS/Verschluesselung aktiv ist.
- Info, ob Zertifikatspruefung oder `TrustServerCertificate` relevant ist.
- Info, ob Zugriff per SQL-Login oder Windows/Domain-Auth erwartet wird.

Berechtigungen:

- mindestens `SELECT`, `INSERT`.
- idealerweise auch `UPDATE` oder `DELETE`, falls Re-Importe/Korrekturen vorgesehen sind.
- Rechte auf:
  - `dbo.vendoc_import_headers`
  - `dbo.vendoc_import_positions`

Fachliche Klaerung:

- Sind diese beiden Tabellen das finale Importschema?
- Welche Spalten sind Pflichtfelder?
- Darf dieselbe Beleg-ID erneut geschrieben werden?
- Wie erkennt VenDoc Dubletten oder Re-Importe?
- Werden Alternativpositionen importiert?
- Werden `0,00`-Positionen importiert?
- Wie genau werden Bilder erwartet?
- Wird `line_total` benoetigt, obwohl die Spalte aktuell nicht sichtbar ist?

## Zieltabellen laut Screenshots

### `dbo.vendoc_import_headers`

| Spalte | Typ laut Screenshot | Null |
| --- | --- | --- |
| `external_document_id` | `uniqueidentifier` | not null |
| `source_document_id` | `nvarchar(max)` | not null |
| `supplier_name` | `nvarchar(max)` | null |
| `supplier_id` | `nvarchar(max)` | null |
| `document_type` | `nvarchar(max)` | null |
| `document_number` | `nvarchar(max)` | null |
| `offer_reference` | `nvarchar(max)` | null |
| `document_date` | `datetime` | null |
| `project_ref` | `nvarchar(max)` | null |
| `currency_code` | `nvarchar(max)` | null |
| `net_total` | `float` | null |
| `vat_total` | `float` | null |
| `gross_total` | `float` | null |
| `is_alternate` | `bit` | null |
| `created_at` | `datetime` | null |
| `subject` | `nvarchar(max)` | null |
| `tax_type` | `nvarchar(max)` | null |
| `customer_id` | `nvarchar(max)` | null |

### `dbo.vendoc_import_positions`

| Spalte | Typ laut Screenshot | Null |
| --- | --- | --- |
| `external_line_item_id` | `uniqueidentifier` | not null |
| `external_document_id` | `nvarchar(max)` | not null |
| `source_line_item_id` | `nvarchar(max)` | not null |
| `position_no` | `nvarchar(max)` | null |
| `item_type` | `nvarchar(max)` | null |
| `is_alternative` | `bit` | null |
| `quantity` | `float` | null |
| `unit_code` | `nvarchar(max)` | null |
| `width_mm` | `float` | null |
| `height_mm` | `float` | null |
| `description_short` | `nvarchar(max)` | null |
| `description_long` | `nvarchar(max)` | null |
| `image_long_text_rtf` | `nvarchar(max)` | null |
| `long_text_rtf` | `nvarchar(max)` | null/optional |
| `unit_price` | `float` | null |
| `page_ref` | `nvarchar(max)` | null |
| `image_is_primary` | `bit` | null |
| `created_at` | `datetime` | null |
| `article_no` | `nvarchar(max)` | null |
| `discount_1` | `float` | null |
| `discount_2` | `float` | null |
| `vat_type` | `nvarchar(max)` | null |
| `unity` | `float` | null |
| `main_line_item_id` | `nvarchar(max)` | null |
| `image_rtf` | `nvarchar(max)` | null/optional |

## Auffaellige Schema-Punkte

1. `external_document_id` ist im Header `uniqueidentifier`, in den Positionen aber `nvarchar(max)`.
2. In `vendoc_import_positions` fehlt aktuell `line_total`.
3. Geldfelder sind `float`, nicht `decimal`. Das kann Rundungsfragen erzeugen.
4. Bilddaten werden nach Dragans `LineItemBase.LongText`-Beispiel als PNG-Hex in einem RTF-Wert uebergeben, nicht als Base64.
5. `main_line_item_id` deutet auf Unterpositionen oder Varianten hin, ist fachlich aber noch offen.
6. `unity` ist `float`; vermutlich ist die fachliche Bedeutung noch zu klaeren.

## VenDoc `LineItemBase`

Dragan hat am 05.05.2026 die Struktur von `LineItemBase` nachgereicht. Diese Tabelle ist die VenDoc-interne Positionstabelle, in die Dragan aus `SRTemp` importiert. Wir schreiben weiterhin nicht direkt in diese Tabelle.

Relevante Felder fuer unser Mapping:

| Spalte | Typ | Bedeutung fuer uns |
| --- | --- | --- |
| `Text` | `nvarchar(255)` | kurzer Positionstext; `description_short` sollte fachlich kurz bleiben |
| `LongText` | `nvarchar(max)` | RTF-LongText; Ziel fuer `image_long_text_rtf` inkl. PNG-Hex |
| `ExternalNumber` | `nvarchar(20)` | moeglicher Zielwert fuer `position_no`, falls Dragan so mappt |
| `Document` | `uniqueidentifier` | VenDoc-interner Dokumentbezug, wird vom Importer gesetzt |
| `Oid`, `CreatedOn`, `CreatedBy`, `Client`, `ObjectType`, `Sort` | diverse | VenDoc-interne Felder, nicht durch unsere App direkt zu setzen |

Konsequenz: Unser SRTemp-Export bleibt passend. Wichtig ist nur, dass der lange technische Text und das Bild vollstaendig in `image_long_text_rtf` landen; `description_long` bleibt zusaetzlich als Plaintext-Quelle erhalten.

## Erstes Mapping aus der Anwendung

### Header-Mapping

| VenDoc-Spalte | Quelle in App | Status |
| --- | --- | --- |
| `external_document_id` | stabile von uns erzeugte UUID | umgesetzt |
| `source_document_id` | `documents.id` als String | klar |
| `supplier_name` | `document.supplier_name` | klar |
| `supplier_id` | Provider-Alias aus App-Mapping | umgesetzt, fachlich pruefen |
| `document_type` | `document.document_type` | klar |
| `document_number` | `document.document_number` | klar |
| `offer_reference` | `document.offer_reference` | klar |
| `document_date` | `document.document_date` | klar |
| `project_ref` | `document.project_ref` | klar |
| `currency_code` | `document.currency` | klar |
| `net_total` | `document.net_total` | klar |
| `vat_total` | `document.vat_total` | klar |
| `gross_total` | `document.gross_total` | klar |
| `is_alternate` | Dokument hat nur Alternativpositionen oder fachliche Regel | offen |
| `created_at` | Exportzeitpunkt | klar |
| `subject` | vermutlich Projekt/Betreff | offen |
| `tax_type` | Steuerlogik | offen |
| `customer_id` | `document.vendoc_customer_number` aus SRTemp-Kundenauswahl | umgesetzt |

### Positions-Mapping

| VenDoc-Spalte | Quelle in App | Status |
| --- | --- | --- |
| `external_line_item_id` | stabile UUID je Position | umgesetzt |
| `external_document_id` | Dokument-UUID | klar, Datentyp beachten |
| `source_line_item_id` | `line_items.id` als String | klar |
| `position_no` | `line_item.position_no` | klar |
| `item_type` | Provider-/Fachregel | offen |
| `is_alternative` | `line_item.is_alternative` | klar |
| `quantity` | `line_item.quantity` | klar |
| `unit_code` | `line_item.unit` | klar |
| `width_mm` | `line_item.width_mm` | klar |
| `height_mm` | `line_item.height_mm` | klar |
| `description_short` | `line_item.description_short` | klar |
| `description_long` | `line_item.description_long` | klar |
| `image_long_text_rtf` | fertiger RTF-LongText inkl. eingebettetem PNG-Hex | bestaetigt |
| `long_text_rtf` | App-Feld `text_only_rtf`, RTF nur mit Positions-Langtext | optional umgesetzt |
| `unit_price` | `line_item.unit_price` | klar |
| `page_ref` | `line_item.page_ref` als String | klar |
| `image_is_primary` | `true`, wenn Bild vorhanden | klar |
| `created_at` | Exportzeitpunkt | klar |
| `article_no` | nicht vorhanden | offen |
| `discount_1` | nicht vorhanden | offen |
| `discount_2` | nicht vorhanden | offen |
| `vat_type` | Steuerregel | offen |
| `unity` | fachliche Bedeutung offen | offen |
| `main_line_item_id` | Unterposition/Hauptposition | offen |
| `image_rtf` | App-Feld `image_only_rtf`, RTF nur mit Bild | optional umgesetzt |

## Technischer Implementierungsplan

### Phase 1 - Dry-Run ohne MSSQL-Zugang

Status: erledigt am 2026-04-29.

Umgesetzt:

- `api/vendoc_exporter.py` erstellen.
- Mapping-Funktion fuer Header und Positionen bauen.
- `image_long_text_rtf` aus Positions-Langtext und primaerem Bild als RTF mit PNG-Hex erzeugen.
- SRTemp-Insert-Script mit `include_sql=true` erzeugen.
- Pflichtfelder vorab validieren.
- `dry_run` API-Endpunkt bauen.
- Tests fuer Mapping mit Sample-Result bauen.

Ergebnis:

- Wir koennen CIBEX/Dragan zeigen, welche Daten geschrieben wuerden, ohne DB-Zugriff zu brauchen.

### Phase 2 - Export-Journal

Status: erledigt am 2026-04-29.

Umgesetzt:

- Postgres-Migration `vendoc_export_jobs`.
- Stabile `external_document_id` speichern.
- Stabile `external_line_item_id` je Position speichern oder deterministisch ableiten.
- Exportstatus und Fehler persistieren.

Ergebnis:

- Re-Export und Fehleranalyse sind moeglich.

### Phase 3 - MSSQL Live-Write

Tasks:

- SQL-Server-Client und Treiber installieren. Status: Dockerfile fuer Microsoft ODBC Driver 18 und `pyodbc` vorbereitet.
- Connection-Builder aus Env. Status: umgesetzt.
- `GET /vendoc/health`. Status: Treiber-/Konfigurationsstatus umgesetzt, echter Connection-Test per `check_connection=true`.
- Transaktionaler Write in Header und Positionen. Status: umgesetzt, bleibt ohne Zugangsdaten deaktiviert.
- Fehlerbehandlung und Rollback. Status: umgesetzt.

Ergebnis:

- Freigegebene Dokumente koennen live in `SRTemp` geschrieben werden.
- Ohne Zielserver-Konfiguration bleibt `VENDOC_MSSQL_ENABLED=false`.
- Je Deployment muss der Live-Write mit VPN/MSSQL-Zugang abgenommen werden.

### Phase 4 - UI

Tasks:

- Mapping-Preview anzeigen. Status: umgesetzt im Admin-/Previewbereich.
- Button `VenDoc Dry-Run`. Status: umgesetzt.
- Button `An VenDoc exportieren`. Status: umgesetzt mit Freigabe-Gate.
- Exportstatus im Dokument anzeigen. Status: umgesetzt via Import-State/latest Job.
- Fehlerdetails anzeigen. Status: umgesetzt.
- Kundenauswahl im Startbereich. Status: umgesetzt.
- Warnung vor erneutem Live-Import. Status: umgesetzt.
- Alternativpositionsmodus im Positionsbereich. Status: umgesetzt.

## Env-Variablen

```env
VENDOC_MSSQL_ENABLED=false
VENDOC_MSSQL_HOST=
VENDOC_MSSQL_PORT=1433
VENDOC_MSSQL_DATABASE=SRTemp
VENDOC_MSSQL_USER=
VENDOC_MSSQL_PASSWORD=
VENDOC_MSSQL_ENCRYPT=true
VENDOC_MSSQL_TRUST_SERVER_CERTIFICATE=false
VENDOC_MSSQL_TIMEOUT_SECONDS=30
VENDOC_MSSQL_DRIVER=ODBC Driver 18 for SQL Server
```

## Regeln fuer Live-Export

1. Dokument muss `status=processed` haben.
2. Dokument muss `approval_status=approved` haben.
3. Mapping muss alle Pflichtfelder liefern.
4. Export wird in `vendoc_export_jobs` protokolliert.
5. Header und Positionen werden in einer MSSQL-Transaktion geschrieben.
6. Bei Fehlern wird nichts teilweise importiert.

## Offene Entscheidungen

1. Soll VenDoc-Dubletten selbst erkennen oder sollen wir Re-Export blockieren?
2. Soll Re-Export alte Zeilen loeschen und neu schreiben?
3. Sollen Alternativpositionen live importiert werden?
4. Sollen `0,00`-Positionen live importiert werden?
5. Wie wird `line_total` uebergeben, falls VenDoc es braucht?
6. Welche Bilder sind Pflicht?
7. Soll pro Position nur ein primaeres Bild oder mehrere Bilder uebergeben werden?
8. Was sind gueltige Werte fuer `tax_type`, `vat_type`, `item_type`?

## Was gut passt

- Trennung Kopf/Positionen passt zum bestehenden Datenmodell.
- Die meisten Kernfelder sind schon vorhanden.
- `source_document_id` und `source_line_item_id` geben Rueckverfolgbarkeit.
- Der fertige VenDoc-RTF-LongText kann aus `line_items.description_long` und dem primaeren Bild aus `document_images.storage_path` erzeugt werden.
- Freigabe-Workflow existiert bereits und kann als Export-Gate genutzt werden.

## Was noch fehlt

- Zielserverzugang/Firewall/VPN je Umgebung pruefen.
- Docker-Image mit installiertem Microsoft ODBC Driver 18 auf dem Ubuntu-Zielserver neu bauen und gegen Zielserver testen.
- Ersten produktionsnahen Live-Write mit anschliessendem SQL-Select gegen `external_document_id` abnehmen.
- Finale fachliche Regeln fuer Sonderfelder, Alternativen, Nullpositionen und Bilder.
- Finale Re-Import-/Dublettenregel mit Dragan/CIBEX.

## Call-Notiz fuer Dragan/CIBEX

> Unsere Anwendung schreibt nach der internen Verarbeitung und Freigabe in eure SQL-Server-Datenbank `SRTemp`.
> Ziel sind `dbo.vendoc_import_headers` und `dbo.vendoc_import_positions`.
> Wir bauen den Export so, dass zuerst ein Dry-Run moeglich ist. Sobald der Zugriff steht, testen wir mit einem echten Datensatz inklusive Bildern.
> Bitte klaert mit CIBEX Host, Port, Login, Firewall, Verschluesselung und ob Re-Imports erlaubt sind.
