# API Referenz (Ist-Stand)

## Basis
- API: `http://localhost:8000`
- Swagger/OpenAPI: `GET /openapi.json` (via FastAPI)

## Endpunkte
1. `GET /health`
- Healthcheck der API

2. `GET /`
- Basis-Info zur laufenden API

3. `POST /upload`
- Multipart Upload
- Form-Field: `file` (PDF)

4. `GET /documents?limit=20`
- Listet zuletzt angelegte Dokumente

5. `POST /process/{document_id}`
- Startet Parsing- und Extraktionspipeline fuer ein Dokument
- Query-Parameter:
  - `process_mode=parser_only|hybrid_fill|llm_override|llm_only` (empfohlen)
  - Backward-compat: `use_llm` + `llm_override` werden weiter akzeptiert

6. `GET /llm-runs/{document_id}?limit=20`
- Listet LLM-Runs eines Dokuments (neueste zuerst)

7. `GET /llm-runs/{document_id}/latest`
- Liefert den neuesten LLM-Run inkl. Feld-Diffs (`changes`)

8. `GET /llm-runs/{document_id}/run/{run_id}`
- Liefert einen bestimmten LLM-Run

9. `GET /compare/{document_id}`
- Fuehrt Parser und LLM separat aus (ohne DB-Write) und liefert Feldvergleich:
  - `parser_snapshot`
  - `llm_snapshot`
  - `comparison[*]` mit `field`, `parser_value`, `llm_value`, `status`
  - `summary` mit Zaehlern (`same`, `different`, `missing_*`)

10. `POST /match-images/{document_id}`
- Bild-Matching pro Position mit Strategien:
  - `strategy=heuristic`
  - `strategy=vlm`
  - `strategy=hybrid` (VLM + Fallback)
- Query-Parameter:
  - `max_candidates` (default `4`)
  - `max_items` (default `60`)
  - `allow_multiple=true|false`
  - `vlm_min_confidence` (default `0.55`)

11. `GET /result/{document_id}`
- Komplettes Ergebnisobjekt:
  - `document`
  - `amount_lines`
  - `line_items`
  - `images`

12. `GET /preview/{document_id}?format=json|csv`
- JSON/CSV Vorschau als direkte Response
- kein Datei-Write nach `data/exports`

13. `GET /export/{document_id}?format=json|csv|sql&include_images_base64=true|false`
- Liefert Download-Response
- schreibt Exportdatei nach `data/exports`

14. `GET /document/{document_id}/file`
- Streamt das Original-PDF inline

15. `GET /document/{document_id}/image/{image_id}`
- Streamt ein extrahiertes Bild inline

16. `GET /ui`
- Browser-Workbench fuer QA/Test

17. `POST /dev/parse-text`
- Dev-Helfer: parser-only gegen freien Text

## Wichtige Result-Felder
### `line_items[*]`
- `page_ref`
- `image_ids`
- `image_ids_primary`
- `image_ids_page_all`
- `image_count`
- `image_count_page_all`

### `images[*]`
- `page_ref`, `image_index`
- `mime_type`, `storage_path`
- `sha256`, `bytes_size`, `width`, `height`
- `is_probably_decorative`, `is_repeated_across_pages`

### `POST /process` Response (LLM-relevant)
- `process_mode_requested`
- `process_mode_effective`
- `llm_requested`
- `llm_enabled_env`
- `llm_used`
- `llm_override`
- `llm_status`
- `llm_model`
- `llm_error`
- `llm_run_id`
- `llm_change_count`
- `llm_change_total`
- `llm_dump_path`

## Beispiel-Calls
```bash
curl -sS http://localhost:8000/health
curl -sS "http://localhost:8000/documents?limit=10"
curl -sS -X POST "http://localhost:8000/process/1?process_mode=hybrid_fill"
curl -sS http://localhost:8000/llm-runs/1/latest
curl -sS "http://localhost:8000/llm-runs/1?limit=10"
curl -sS http://localhost:8000/compare/1
curl -sS -X POST "http://localhost:8000/match-images/1?strategy=hybrid"
curl -sS http://localhost:8000/result/1
curl -sS "http://localhost:8000/preview/1?format=json"
curl -sS "http://localhost:8000/export/1?format=csv"
```
