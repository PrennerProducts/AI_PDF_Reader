# KI-PDF-Reader On-Prem PoC

## Quickstart (Infra v1)

```bash
cd infra
cp .env.example .env
docker compose up -d --build
```

## One-Terminal Live Mode

```bash
./infra/dev-watch.sh
```

Starts/recreates the stack, runs quick health checks, then streams all container logs in one terminal.

## Live API Canary

```bash
./infra/api-canary.sh
```

Runs a fixed provider canary set against the live API stack and fails fast if supplier, document number, date, position count, or validation status drift.

## New Provider Scaffold

```bash
./infra/new-provider.sh muster_anbieter "Muster Anbieter GmbH"
```

Creates the template module, sample folders, onboarding note, and registry entry for a new provider.

## Verify

```bash
curl http://localhost:8000/health
curl http://localhost:11435/api/tags
```

## GPU Check (Host)

```bash
nvidia-smi
```

## Pull model

```bash
docker exec -it pdr-ollama ollama pull qwen2.5:7b-instruct
```

## Current focus
1. Validierungsflags im Result (Pflichtfelder, Summenkonsistenz, Auffaelligkeiten)
2. Regressionstests fuer die 3 Sample-PDFs (Parser, Export, Bildmapping)
3. ERP-Zielmapping finalisieren (Pflichtfelder, Alternativpositionen, 0,00-Positionen)

## API (current)
- `GET /health`
- `GET /ui` (Web-Workbench fuer PDF + Extraction Vergleich)
- `POST /upload` (multipart form-data, field `file`)
- `POST /process/{document_id}?process_mode=parser_only|hybrid_fill|llm_override|llm_only`
- `GET /compare/{document_id}` (Parser vs LLM Feldvergleich)
- `POST /match-images/{document_id}?strategy=heuristic|vlm|hybrid`
- `GET /llm-runs/{document_id}?limit=20`
- `GET /llm-runs/{document_id}/latest`
- `GET /llm-runs/{document_id}/run/{run_id}`
- `GET /documents?limit=20`
- `GET /result/{document_id}`
- `GET /preview/{document_id}?format=json|csv` (Preview ohne Export-Datei)
- `GET /document/{document_id}/file` (inline PDF stream)
- `GET /document/{document_id}/image/{image_id}` (inline image stream)
- `GET /export/{document_id}?format=json|csv|sql&include_images_base64=true|false`
- `POST /dev/parse-text`

## DB migrations
- SQL migrations are located in `api/migrations/`.
- Migrations are applied automatically on API startup.
- Applied versions are tracked in table `schema_migrations`.

## LLM settings
- `LLM_ENABLED=true|false`
- `LLM_TIMEOUT_SECONDS=120`
- `LLM_MAX_TEXT_CHARS=8000`
- `OLLAMA_BASE_URL` and `OLLAMA_MODEL` are used for Ollama inference.
- `VLM_ENABLED=true|false` (Bild-Matching mit Vision-LLM)
- `OLLAMA_VLM_MODEL` (z. B. `qwen2.5vl:7b`)
- `VLM_TIMEOUT_SECONDS=90`

## Processing modes
- `parser_only`: nur parser/extractor
- `hybrid_fill`: parser-first, LLM fuellt nur fehlende Felder
- `llm_override`: parser + LLM, LLM darf Felder ueberschreiben
- `llm_only`: nur LLM fuer Kopffelder/Summen (Positionen/Bilder bleiben parserbasiert)

## Documentation
- `docs/README.md`
- `docs/PLAN.md`
- `docs/STATUS.md`
- `docs/HOW_IT_WORKS.md`
- `docs/API.md`
- `docs/PROVIDER_ONBOARDING.md`

## Data dirs
- `data/uploads`
- `data/exports`
- `data/logs`
