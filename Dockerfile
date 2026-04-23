# =============================================================================
# AegisHarness — Backend Dockerfile
# =============================================================================
# Multi-stage build:
#   Stage 1 (builder)  — install Python deps into a venv
#   Stage 2 (runtime)  — copy only the venv + source; no build tools
#
# Build:   docker build -t harness-backend .
# Run:     docker run -p 8000:8000 --env-file .env harness-backend
# =============================================================================

# ---------- Stage 1: dependency builder ----------
FROM python:3.12-slim AS builder

WORKDIR /build

# System deps required by some Python packages (psycopg2 build, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create an isolated venv so we can copy it cleanly to the runtime stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt


# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# Copy venv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Non-root user for security
RUN useradd -m -u 1000 harness
USER harness

WORKDIR /app

# Copy application source (excludes files matched by .dockerignore)
COPY --chown=harness:harness . .

# Workspaces volume — generated files survive container restarts when mounted
VOLUME ["/app/workspaces"]

EXPOSE 8000

# Uvicorn with multiple workers; adjust --workers for production
CMD ["uvicorn", "api.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "2", \
     "--timeout-keep-alive", "75"]
