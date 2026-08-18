# Trial II — the pre-review verification image.
#
# A disposable container with the full repo toolchain (mise, poetry, aube,
# hk, Playwright + Chromium) so an agent — or anyone without the host setup —
# can run the local gauntlet against a checkout before review:
#
#   docker build -f docker/verification.Dockerfile -t ludamus-verify .
#   docker run --rm ludamus-verify run verify
#
# Dependency layers cache on the lockfiles; only the final checkout copy
# changes between branches. Never used by deploys — that's docker/Dockerfile.
# Context filtering lives in docker/verification.Dockerfile.dockerignore
# (per-Dockerfile ignore; the root .dockerignore stays deploy-shaped).
FROM jdxcode/mise:2026.2

# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends gettext curl git lsof \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
# Browsers install once here as root and stay readable for any later user.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers

WORKDIR /work

# Dependency manifests first: a source-only change reuses every layer up to
# the final checkout copy.
COPY mise.toml tasks.toml python_tasks.toml pyproject.toml poetry.lock ./
COPY .npmrc aube-workspace.yaml aube-lock.yaml package.json ./
COPY src/ludamus/client/package.json ./src/ludamus/client/
COPY tests/e2e/package.json ./tests/e2e/

RUN mise trust && mise install
RUN mise exec -- poetry install --no-root
RUN mise exec -- aube install --frozen-lockfile
RUN mise exec -- aube exec -C tests/e2e playwright install --with-deps chromium

# The checkout under verification.
COPY . .

RUN mise exec -- poetry install

# Base image entrypoint is ["mise"]; `verify` is the Trial II gauntlet task
# defined in mise.toml (hk, pytest on SQLite, Playwright e2e).
CMD ["run", "verify"]
