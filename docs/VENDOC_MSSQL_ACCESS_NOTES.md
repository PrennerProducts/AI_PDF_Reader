# VenDoc MSSQL Import: Zugriff, Mapping, Call-Notizen

Stand: 2026-04-27

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
| `unit_price` | `float` | null |
| `page_ref` | `nvarchar(max)` | null |
| `image_mime_type` | `nvarchar(max)` | null |
| `image_filename` | `nvarchar(max)` | null |
| `image_base64` | `nvarchar(max)` | null |
| `image_is_primary` | `bit` | null |
| `created_at` | `datetime` | null |
| `article_no` | `nvarchar(max)` | null |
| `discount_1` | `float` | null |
| `discount_2` | `float` | null |
| `vat_type` | `nvarchar(max)` | null |
| `unity` | `float` | null |
| `main_line_item_id` | `nvarchar(max)` | null |

## Auffaellige Schema-Punkte

1. `external_document_id` ist im Header `uniqueidentifier`, in den Positionen aber `nvarchar(max)`.
2. In `vendoc_import_positions` fehlt aktuell `line_total`.
3. Geldfelder sind `float`, nicht `decimal`. Das kann Rundungsfragen erzeugen.
4. Bilddaten liegen direkt auf Positionsebene als Base64.
5. `main_line_item_id` deutet auf Unterpositionen oder Varianten hin, ist fachlich aber noch offen.
6. `unity` ist `float`; vermutlich ist die fachliche Bedeutung noch zu klaeren.

## Erstes Mapping aus der Anwendung

### Header-Mapping

| VenDoc-Spalte | Quelle in App | Status |
| --- | --- | --- |
| `external_document_id` | stabile von uns erzeugte UUID | zu implementieren |
| `source_document_id` | `documents.id` als String | klar |
| `supplier_name` | `document.supplier_name` | klar |
| `supplier_id` | noch nicht vorhanden | offen |
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

### Positions-Mapping

| VenDoc-Spalte | Quelle in App | Status |
| --- | --- | --- |
| `external_line_item_id` | stabile UUID je Position | zu implementieren |
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
| `unit_price` | `line_item.unit_price` | klar |
| `page_ref` | `line_item.page_ref` als String | klar |
| `image_mime_type` | primaeres Bild | klar |
| `image_filename` | generiert aus Dokument/Position/Bild | zu implementieren |
| `image_base64` | primaeres Bild Base64 | zu implementieren |
| `image_is_primary` | `true`, wenn Bild vorhanden | klar |
| `created_at` | Exportzeitpunkt | klar |
| `article_no` | nicht vorhanden | offen |
| `discount_1` | nicht vorhanden | offen |
| `discount_2` | nicht vorhanden | offen |
| `vat_type` | Steuerregel | offen |
| `unity` | fachliche Bedeutung offen | offen |
| `main_line_item_id` | Unterposition/Hauptposition | offen |

## Technischer Implementierungsplan

### Phase 1 - Dry-Run ohne MSSQL-Zugang

Tasks:

- `api/vendoc_exporter.py` erstellen.
- Mapping-Funktion fuer Header und Positionen bauen.
- Base64 aus primaerem Bild lesen.
- Pflichtfelder vorab validieren.
- `dry_run` API-Endpunkt bauen.
- Tests fuer Mapping mit Sample-Result bauen.

Ergebnis:

- Wir koennen CIBEX/Dragan zeigen, welche Daten geschrieben wuerden, ohne DB-Zugriff zu brauchen.

### Phase 2 - Export-Journal

Tasks:

- Postgres-Migration `vendoc_export_jobs`.
- Stabile `external_document_id` speichern.
- Stabile `external_line_item_id` je Position speichern oder deterministisch ableiten.
- Exportstatus und Fehler persistieren.

Ergebnis:

- Re-Export und Fehleranalyse sind moeglich.

### Phase 3 - MSSQL Live-Write

Tasks:

- SQL-Server-Client und Treiber installieren.
- Connection-Builder aus Env.
- `GET /vendoc/health`.
- Transaktionaler Write in Header und Positionen.
- Fehlerbehandlung und Rollback.

Ergebnis:

- Freigegebene Dokumente koennen live in `SRTemp` geschrieben werden.

### Phase 4 - UI

Tasks:

- Mapping-Preview anzeigen.
- Button `VenDoc Dry-Run`.
- Button `An VenDoc exportieren`.
- Exportstatus im Dokument anzeigen.
- Fehlerdetails anzeigen.

## Geplante Env-Variablen

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
- Base64-Bilder koennen aus `document_images.storage_path` erzeugt werden.
- Freigabe-Workflow existiert bereits und kann als Export-Gate genutzt werden.

## Was noch fehlt

- MSSQL-Zugangsdaten.
- MSSQL-Treiber/Client im Docker-Image.
- VenDoc-Mapping-Code.
- Export-Journal.
- Live-Write-Endpunkt.
- UI fuer Exportstatus.
- Finale fachliche Regeln fuer Sonderfelder, Alternativen, Nullpositionen und Bilder.

## Call-Notiz fuer Dragan/CIBEX

> Unsere Anwendung schreibt nach der internen Verarbeitung und Freigabe in eure SQL-Server-Datenbank `SRTemp`.
> Ziel sind `dbo.vendoc_import_headers` und `dbo.vendoc_import_positions`.
> Wir bauen den Export so, dass zuerst ein Dry-Run moeglich ist. Sobald der Zugriff steht, testen wir mit einem echten Datensatz inklusive Bildern.
> Bitte klaert mit CIBEX Host, Port, Login, Firewall, Verschluesselung und ob Re-Imports erlaubt sind.
