# =============================================================================
# Dockerfile — board-report-generator
# Target: Azure App Service (Linux, B1) — Python 3.11 scheduled pipeline
# Strategy: Multi-stage build (builder → runtime) for a lean production image
# =============================================================================

# ── Stage 1: Dependency builder ───────────────────────────────────────────────
# Compiles Python wheels in an image that has gcc. The compiled wheels are
# then copied to the runtime stage — no compiler in the final image.
FROM python:3.11-slim AS builder

WORKDIR /build

# gcc is only needed to compile native extensions (e.g. numpy C extensions
# when a pre-compiled wheel isn't available for the target platform).
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir --upgrade pip \
    && pip wheel \
        --no-cache-dir \
        --wheel-dir=/wheels \
        -r requirements.txt


# ── Stage 2: Production runtime ───────────────────────────────────────────────
FROM python:3.11-slim AS runtime

# OCI image labels (visible in ACR portal and docker inspect)
LABEL org.opencontainers.image.title="Board Report Generator" \
      org.opencontainers.image.description="Automated CFO board pack: PDF + Excel + Dashboard" \
      org.opencontainers.image.url="https://github.com/marwane019/board-report-generator" \
      org.opencontainers.image.source="https://github.com/marwane019/board-report-generator" \
      org.opencontainers.image.licenses="MIT"

# ── Environment variables ─────────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    # Don't buffer stdout/stderr — ensures logs appear in App Service Log Stream
    PYTHONUNBUFFERED=1 \
    # Non-interactive matplotlib backend — no display server needed in container
    MPLBACKEND=Agg \
    # Add /app to PYTHONPATH so `from src.metrics import ...` works anywhere
    PYTHONPATH=/app \
    # Default port (App Service overrides this with $PORT at runtime)
    PORT=8000

WORKDIR /app

# ── Runtime system dependencies ───────────────────────────────────────────────
# libgomp1 — GNU OpenMP runtime, required by numpy (used by matplotlib/pandas)
#             even when the Agg (non-display) backend is selected.
# curl      — used by the Docker HEALTHCHECK instruction below.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgomp1 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Install Python packages from pre-built wheels ────────────────────────────
# No compiler needed in the runtime stage — all native code is pre-compiled.
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# ── Copy application source ───────────────────────────────────────────────────
# .dockerignore prevents dev artifacts, secrets, and generated outputs
# from being copied into the image.
COPY . .

# ── Runtime directory setup ───────────────────────────────────────────────────
# These directories are written to at runtime (CSVs, PDFs, logs).
# On App Service the filesystem is ephemeral — outputs are emailed/Slacked
# immediately after generation, so persistence is not required.
RUN mkdir -p data/raw data/processed data/output logs

# ── Non-root user (security best practice) ───────────────────────────────────
RUN addgroup --system appgroup \
    && adduser --system --ingroup appgroup --no-create-home appuser \
    && chown -R appuser:appgroup /app

USER appuser

# ── Port ─────────────────────────────────────────────────────────────────────
# App Service injects $PORT at runtime; EXPOSE documents the default.
EXPOSE ${PORT}

# ── Docker-level health check ─────────────────────────────────────────────────
# App Service has its own health probe (configured separately), but this
# also causes `docker ps` to show HEALTHY and restarts the container if
# the health server dies unexpectedly.
#
# --start-period=60s  gives the scheduler time to import heavy libraries
#                     (pandas, matplotlib, reportlab) before the first probe.
HEALTHCHECK \
    --interval=2m \
    --timeout=15s \
    --start-period=60s \
    --retries=3 \
    CMD curl -sf "http://localhost:${PORT}/health" || exit 1

# ── Entrypoint ───────────────────────────────────────────────────────────────
# entrypoint.py starts:
#   1. HTTP health server on a daemon thread (satisfies App Service probing)
#   2. APScheduler daemon on the main thread (fires Monday 06:00 London)
CMD ["python", "entrypoint.py"]
