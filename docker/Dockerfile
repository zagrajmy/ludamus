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
COPY tasks.toml pyproject.toml poetry.lock docker/mise.toml /app/

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser

# Create necessary directories and set ownership
RUN mkdir -p staticfiles media logs \
    && chown -R appuser:appuser /app \
    && chown -R appuser:appuser /mise

# Development stage with dev dependencies
FROM base AS dev

COPY docker/Procfile.dev /app/

# Switch to non-root user
USER appuser

# Install toolchain and Python dependencies (cached independently of src changes)
RUN mise trust && mise install && mise run install

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

# Switch to non-root user
USER appuser

# Install toolchain and production Python dependencies (cached independently of src changes)
RUN mise trust && mise install && mise run install --only main

# Copy application code
COPY --chown=appuser:appuser src ./src

# Run Django commands that need source code
RUN mise run build-frontend && mise run dj compilemessages

# Expose port
EXPOSE 8000

# Start gunicorn (migrations are handled by the compose migrations service)
CMD ["run", "gunicorn"]
