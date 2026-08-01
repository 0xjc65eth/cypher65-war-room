# ── CYPHER65 War Room · Production image ─────────────────────────────────
# Multi-stage build: deps in one layer, runtime image stays small.
# The app is a self-contained Flask + SQLite deployment (no external DB
# required). Optional InfluxDB mirroring is configured at runtime via env.
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ── Stage 1: runtime deps ────────────────────────────────────────────────
FROM base AS runtime

RUN groupadd --system cypher && useradd --system --gid cypher cypher

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=cypher:cypher . .

# Persistent data (SQLite) lives in /app/data; make it writable.
RUN mkdir -p /app/data && chown -R cypher:cypher /app/data

USER cypher

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/api/healthz', timeout=4).status==200 else 1)"

CMD ["python", "app.py"]
