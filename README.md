# KI-PDF-Reader On-Prem PoC

## Quickstart (Infra v1)

```bash
cd infra
cp .env.example .env
docker compose up -d
```

## Verify

```bash
curl http://localhost:8000/health
curl http://localhost:11434/api/tags
```

## GPU Check (Host)

```bash
nvidia-smi
```

## Pull model

```bash
docker exec -it pdr-ollama ollama pull qwen2.5:7b-instruct
```

## Next steps
1. Upload endpoint + storage structure
2. OCR + parser pipeline
3. Validation + confidence
4. JSON/CSV/SQL export

## Data dirs
- `data/uploads`
- `data/exports`
- `data/logs`
