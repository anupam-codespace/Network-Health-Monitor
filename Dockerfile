# Multi-stage Dockerfile for NetWatch
FROM python:3.12-slim AS builder

WORKDIR /build

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.4.29 /uv /bin/uv

# Copy project manifests and install dependencies into a dedicated venv
COPY pyproject.toml README.md ./
RUN uv venv /opt/venv && \
    uv pip install --no-cache --python /opt/venv/bin/python ".[dev]"

# Final runtime image
FROM python:3.12-slim AS runner

WORKDIR /app

# Install curl for container HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root system user and group
RUN groupadd -r -g 1001 netwatch && \
    useradd -r -u 1001 -g netwatch -d /app -s /sbin/nologin netwatch

# Copy virtual environment and application code
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY alembic.ini ./
COPY alembic ./alembic
COPY targets.yaml ./
COPY netwatch ./netwatch

# Assign ownership to non-root user
RUN chown -R netwatch:netwatch /app

USER netwatch

EXPOSE 8001

HEALTHCHECK --interval=5s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/healthz || exit 1

CMD ["uvicorn", "netwatch.main:app", "--host", "0.0.0.0", "--port", "8001"]
