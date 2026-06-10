# =============================================================================
# Dockerfile — Plateforme RH
# Multi-stage build : builder → production
# =============================================================================

FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev libcairo2-dev libpango-1.0-0 libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 libffi-dev shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ── Production ────────────────────────────────────────────────────────────
FROM python:3.11-slim AS production

RUN groupadd -r hrapp && useradd -r -g hrapp hrapp
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /root/.local /home/hrapp/.local
ENV PATH=/home/hrapp/.local/bin:$PATH

COPY --chown=hrapp:hrapp . .
RUN mkdir -p /app/storage/uploads /app/logs && chown -R hrapp:hrapp /app

USER hrapp
EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')"

CMD ["gunicorn", "--worker-class", "gevent", "--workers", "4", \
     "--bind", "0.0.0.0:5000", "--timeout", "120", \
     "--access-logfile", "-", "--error-logfile", "-", "wsgi:application"]
