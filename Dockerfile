# ─────────────────────────────────────────────────────────────────────────────
# Data Marketplace + Applications FastAPI backend — multi-stage build.
# Build context is the `backend_fastapi/` directory (see compose.yml).
# The container listens on :8000 (parity with the .NET backend / frontend proxy).
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps: libpq for asyncpg, curl for healthchecks.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the package source first so the editable/real install picks up the `dmp`
# package (hatchling builds the wheel from src/dmp).
COPY pyproject.toml ./
COPY src/ ./src/

RUN pip install --upgrade pip && pip install .

# Migrations + Alembic config (not needed for the wheel, used at runtime).
COPY migrations/ ./migrations/
COPY alembic.ini ./

EXPOSE 8000

# Run uvicorn importing the app factory from src/dmp/main.py.
ENV BACKEND_PORT=8000 \
    PYTHONPATH=/app/src
CMD ["sh", "-c", "uvicorn dmp.main:app --host 0.0.0.0 --port ${BACKEND_PORT:-8000}"]
