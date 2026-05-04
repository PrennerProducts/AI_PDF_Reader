#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "[info] Created infra/.env from .env.example"
fi

echo "[1/4] Building and starting stack..."
docker compose up -d --build --force-recreate

echo "[2/4] Waiting for API health..."
for _ in $(seq 1 90); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

echo "[3/4] Quick checks"
echo "API:    $(curl -fsS http://localhost:8000/health)"

echo "[4/4] Live logs (Ctrl+C to stop log stream, containers keep running)"
docker compose logs -f --tail=120
