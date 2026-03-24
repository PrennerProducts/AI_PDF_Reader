FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY api/pyproject.toml /tmp/api-src/pyproject.toml
COPY api/*.py /tmp/api-src/
RUN pip install --upgrade pip && pip install /tmp/api-src

COPY api/ /app/

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
