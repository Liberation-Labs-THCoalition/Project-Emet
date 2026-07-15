# Emet — Investigative Intelligence Framework
# Multi-stage build: dependencies first (cached), then application code.

# --- Build stage ---
FROM python:3.12-slim AS builder
WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY emet/__init__.py emet/__init__.py
RUN pip install --no-cache-dir --prefix=/install ".[prod]" 2>/dev/null || \
    pip install --no-cache-dir --prefix=/install .

# --- Runtime stage ---
FROM python:3.12-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && \
    rm -rf /var/lib/apt/lists/*

RUN addgroup --system emet && adduser --system --ingroup emet emet

COPY --from=builder /install /usr/local

COPY emet/ emet/
COPY migrations/ migrations/
COPY alembic.ini .
COPY VALUES.json .
COPY skills/ skills/

RUN mkdir -p /app/investigations /app/data && \
    chown -R emet:emet /app

USER emet

EXPOSE 8000 9400

HEALTHCHECK --interval=30s --timeout=5s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "emet.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
