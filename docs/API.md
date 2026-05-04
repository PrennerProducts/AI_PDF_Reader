# API Referenz

Stand: 2026-04-29

## Basis

- API: `http://localhost:8000`
- UI: `GET /ui`
- OpenAPI JSON: `GET /openapi.json`

## Dokumente

### `POST /upload`

Laedt ein PDF hoch.

- Multipart Form Field: `file`
- Nur `.pdf` wird akzeptiert.
- Legt einen Datensatz in `documents` mit `status=uploaded` an.

### `GET /documents?limit=20`

Listet zuletzt angelegte Dokumente.

### `GET /document/{document_id}/file`

Streamt das Original-PDF inline.

### `POST /reset/{document_id}?delete_logs=true`

Loescht extrahierte Ergebnisse eines Dokuments.

- Upload-Datei bleibt erhalten.
- Optional werden Text- und Bildlogs geloescht.
- Dokument wird wieder auf `uploaded` gesetzt.

## Verarbeitung

### `POST /process/{document_id}`

Startet die Extraktionspipeline.

Query-Parameter:

- `process_mode=parser_only`

Modi:

- `parser_only`: lokaler Parser, lokaler Text-/Bildextraktor und heuristische Bildzuordnung.

Hinweis: KI-/Modellverarbeitung ist im Produktbetrieb deaktiviert. Alte Parameter wie
`use_llm=true` oder nicht erlaubte `process_mode`-Werte werden mit HTTP `400` abgelehnt.

### `GET /progress/{document_id}`

Liefert den aktuellen Processing-Fortschritt.

Hinweis: Der Fortschritt ist aktuell in-memory und damit noch nicht produktionsrobust.

### `GET /result/{document_id}`

Liefert das normalisierte Ergebnis:

- `document`
- `document_relations`
- `amount_lines`
- `line_items`
- `images`
- `validation`

### `GET /relations/{document_id}`

Liefert die logische Dokumentverknuepfung:

- `linked_offer_document`: bei Auftragsbestaetigungen das zugehoerige Angebot, falls gefunden.
- `linked_order_confirmations`: bei Angeboten die verknuepften Auftragsbestaetigungen.

## Review und Freigabe

### `POST /documents/{document_id}/line-items/{line_item_id}/assign-image`

Setzt ein finales Bild fuer eine Position.

Body:

```json
{"image_id": 123}
```

### `DELETE /documents/{document_id}/line-items/{line_item_id}/assign-image`

Markiert bewusst, dass eine Position kein finales Bild hat.

### `POST /documents/{document_id}/line-items/{line_item_id}/review-check`

Markiert offene Warnungen einer Position als manuell geprueft.

### `DELETE /documents/{document_id}/line-items/{line_item_id}/review-check`

Setzt die manuelle Positionspruefung zurueck.

### `POST /documents/{document_id}/approval`

Gibt ein Dokument frei.

Regel:

- Dokument muss `status=processed` haben.
- Validierung muss `auto_accept` oder `manual_checked` sein.

Body:

```json
{
  "reviewer_name": "Name",
  "note": "Optionale Freigabenotiz"
}
```

### `DELETE /documents/{document_id}/approval`

Setzt die Dokumentfreigabe zurueck.

## Export und Preview

### `GET /preview/{document_id}?format=json|csv`

Liefert JSON/CSV direkt als Response.

- Kein Datei-Write nach `data/exports`.

### `GET /export/{document_id}?format=json|csv|sql&include_images_base64=true|false`

Liefert Download-Response und schreibt Datei nach `data/exports`.

Wichtig:

- Der aktuelle `sql` Export ist ein Export fuer das interne App-Schema.
- Er ist noch kein VenDoc/MSSQL-Import.

## VenDoc

### `POST /vendoc/export/{document_id}?dry_run=true|false&include_sql=false`

Erzeugt ein VenDoc-Mapping fuer das Dokument und schreibt einen Eintrag in `vendoc_export_jobs`.

Dry-Run:

- baut `header`, `positions`, `warnings`, `errors` und `summary`.
- erzeugt je Position `image_long_text_rtf` als VenDoc-RTF-LongText; das primaere Positionsbild wird darin als PNG-Hex eingebettet.
- liefert mit `include_sql=true` ein SRTemp-Insert-Script fuer `dbo.vendoc_import_headers` und `dbo.vendoc_import_positions`.
- benoetigt keinen MSSQL-Zugriff.
- ist auch vor Dokumentfreigabe nutzbar.

Live-Export:

- ist nur bei `document.status=processed` und `approval_status=approved` erlaubt.
- liefert fuer nicht freigegebene Dokumente HTTP `409`.
- bleibt aktuell mit HTTP `503`/`501` gesperrt, bis CIBEX-Zugriff und MSSQL-Writer verfuegbar sind.

### `GET /vendoc/export-jobs/{document_id}?limit=20&include_payload=false`

Listet VenDoc-Exportversuche und Dry-Runs eines Dokuments.

### `GET /vendoc/export-jobs/{document_id}/latest?include_payload=false`

Liefert den letzten VenDoc-Exportjob eines Dokuments.

### `GET /vendoc/health`

Liefert Konfigurationsstatus fuer den geplanten MSSQL-Zielzugriff. Der Live-Write ist aktuell noch nicht verfuegbar.

## Bilder

### `GET /document/{document_id}/image/{image_id}`

Streamt ein extrahiertes Bild inline.

- Nicht browserfaehige Bildformate werden serverseitig als PNG-Vorschau ausgeliefert, wenn moeglich.

### `POST /match-images/{document_id}`

Berechnet Bild-Matching pro Position.

Query-Parameter:

- `strategy=heuristic`
- `max_candidates`
- `max_items`
- `allow_multiple`

## Dev

### `POST /dev/parse-text`

Parser-only gegen freien Text.

## Wichtige Result-Felder

### `document`

- `id`
- `supplier_name`
- `document_type`
- `offer_reference`
- `document_number`
- `document_date`
- `project_ref`
- `currency`
- `net_total`
- `vat_total`
- `gross_total`
- `parse_confidence`
- `approval_status`
- `reviewed_by`
- `reviewed_at`
- `approval_note`
- `status`

### `line_items[*]`

- `id`
- `position_no`
- `lv_pos`
- `is_alternative`
- `quantity`
- `unit`
- `width_mm`
- `height_mm`
- `description_short`
- `description_long`
- `unit_price`
- `line_total`
- `page_ref`
- `confidence`
- `image_ids`
- `image_ids_primary`
- `image_candidate_ids`
- `image_count`
- `validation_status`
- `validation_issues`
- `review_checked`

### `images[*]`

- `id`
- `page_ref`
- `image_index`
- `mime_type`
- `storage_path`
- `sha256`
- `bytes_size`
- `width`
- `height`
- `is_probably_decorative`
- `is_repeated_across_pages`
- `is_assigned`
- `assigned_line_item_ids`
- `assigned_position_nos`

### `validation`

- `status=auto_accept|manual_checked|review|reject`
- `issue_count`
- `error_count`
- `warning_count`
- `required_fields`
- `recommended_fields`
- `document_issues`
- `totals`
- `line_item_summary`
- `image_summary`
- `approval`

## Beispiel-Calls

```bash
curl -sS http://localhost:8000/health
curl -sS "http://localhost:8000/documents?limit=10"
curl -sS -X POST "http://localhost:8000/process/1?process_mode=parser_only"
curl -sS http://localhost:8000/progress/1
curl -sS http://localhost:8000/result/1
curl -sS -X POST "http://localhost:8000/match-images/1?strategy=heuristic"
curl -sS "http://localhost:8000/preview/1?format=json"
curl -sS "http://localhost:8000/export/1?format=csv"
curl -sS -X POST "http://localhost:8000/vendoc/export/1?dry_run=true"
curl -sS "http://localhost:8000/vendoc/export-jobs/1/latest"
```
