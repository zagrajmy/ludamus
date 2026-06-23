# Multi-stage Dockerfile for development and production

# Base stage with common setup
FROM jdxcode/mise:2026.2 AS base

# Install system dependencies
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends gettext curl && rm -rf /var/lib/apt/lists/*

ARG DJANGO_SETTINGS_MODULE
ARG ENV

ENV DJANGO_SETTINGS_MODULE=${DJANGO_SETTINGS_MODULE}
ENV ENV=${ENV}
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONPATH=src
ENV PYTHONUNBUFFERED=1
# Build-only: Django settings need these to load for compilemessages.
# Overridden at runtime by env_file / environment in compose.
ENV SECRET_KEY=build-only-not-used-at-runtime
ENV CREDENTIALS_ENCRYPTION_KEY=build-only-not-used-at-runtime
ENV DB_NAME=:memory:

# Set work directory
WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml poetry.lock docker/mise.toml /app/

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Create necessary directories and set ownership
RUN mkdir -p staticfiles media logs \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /mise

# Switch to non-root user for the remaining build steps
USER appuser

# Install the toolchain (python/node/poetry/aube). Shared by dev and prod; the
# Python *dependencies* are installed per-stage below because they differ
# (dev installs all groups, prod only main).
RUN mise trust && mise install

# Install frontend deps reproducibly from the aube workspace lockfile, scoped to
# the client package. Copy only the manifests + lockfile first so a source-only
# change reuses this cached node_modules layer. tests/e2e/package.json is needed
# for the frozen-lockfile workspace integrity check even though --filter +
# --no-optional keep its (Playwright) deps out of the image. Independent of the
# Python deps, so it lives in base and is built once for both stages.
COPY --chown=appuser:appuser aube-workspace.yaml aube-lock.yaml package.json ./
COPY --chown=appuser:appuser tests/e2e/package.json ./tests/e2e/
COPY --chown=appuser:appuser src/ludamus/client/package.json ./src/ludamus/client/
# Retry to ride out transient registry stream errors: this install pulls from
# the npm registry over the host's network, which occasionally stalls mid-stream
# ("error decoding response body") and fails the whole deploy. aube caches what
# it already fetched, so each retry resumes near where the last attempt stopped.
RUN n=1; until mise run frontend-deps; do \
        if [ "$n" -ge 5 ]; then echo "frontend-deps failed after $n attempts" >&2; exit 1; fi; \
        echo "frontend-deps attempt $n failed; retrying in $((n * 10))s" >&2; \
        sleep "$((n * 10))"; \
        n=$((n + 1)); \
    done

# Development stage with dev dependencies
FROM base AS dev

COPY docker/Procfile.dev /app/

# Install Python dependencies (all groups)
RUN mise run p install

# Copy application code
COPY --chown=appuser:appuser src ./src

# Run Django commands that need source code
RUN mise run build-frontend && mise run dj compilemessages

# Expose port
EXPOSE 8000

# Development command - runserver with reload
# Base image (jdxcode/mise) sets ENTRYPOINT ["mise"]
CMD ["run", "start"]

# Production stage without dev dependencies
FROM base AS prod

# Install production Python dependencies only
RUN mise run p install --only main

# Copy application code
COPY --chown=appuser:appuser src ./src

# Run Django commands that need source code
RUN mise run build-frontend && mise run dj compilemessages

# Expose port
EXPOSE 8000

# Start gunicorn (migrations are handled by the compose migrations service)
CMD ["run", "gunicorn"]
