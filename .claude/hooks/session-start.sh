#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo '{"async": true, "asyncTimeout": 600000}'

cd "$CLAUDE_PROJECT_DIR"

export PATH="$HOME/.local/bin:$PATH"

# Write the commit-credit guidance FIRST, before any install/network step that
# can fail. Crediting the human who drove the session must not depend on a
# successful bootstrap — when an install fails under `set -e`, everything below
# it is skipped, so this has to come before that risk, not after it.
if ! grep -q '^## Commits$' CLAUDE.local.md 2>/dev/null; then
  # Credit whoever is driving this session, not Claude/Anthropic. The trailer
  # name is the email local-part (best-effort); GitHub attributes by email.
  human_email="${CLAUDE_CODE_USER_EMAIL:-}"
  if [ -n "$human_email" ]; then
    printf '@CLAUDE.md\n\n## Commits\n\nCo-author the human, not Claude/Anthropic. End commits with:\n\n    Co-authored-by: %s <%s>\n' \
      "${human_email%@*}" "$human_email" >> CLAUDE.local.md
  else
    printf '@CLAUDE.md\n\n## Commits\n\nCo-author the human driving this session, not Claude/Anthropic.\n' >> CLAUDE.local.md
  fi
fi

# The sandbox egress proxy 403s every GitHub download, so activate the
# `sandbox` mise config environment: mise.sandbox.toml swaps each
# GitHub-release tool for the same version from a reachable registry.
export MISE_ENV=sandbox

# Put mise-managed tool shims (aubx -> agent-browser, ast-grep, poetry, node,
# markdownlint-cli2, ...) on PATH for every shell in the session, so tools
# resolve directly instead of needing `mise exec`/activation per command.
# Persisted for the session via CLAUDE_ENV_FILE, together with MISE_ENV so
# every later `mise` invocation keeps loading mise.sandbox.toml.
#
# PREPEND, don't append — and shims must precede ~/.local/bin: mise inserts
# its managed paths (incl. the .venv activation from `_.python.venv`) at the
# shims' position in PATH, while the container image ships uv-tool builds of
# pytest/mypy/black/poetry in ~/.local/bin. If ~/.local/bin wins, those
# plugin-less binaries shadow the .venv ones inside every `mise run`/`mise x`
# (pytest has no django, mypy has no mypy_django_plugin); if the shims are
# appended, the venv lands after the container's bare /usr/local/bin/python
# and every `mise run` task fails with "No module named 'django'".
# `.venv/bin` sits between them because mise cannot shim the interpreter here:
# mise.sandbox.toml disables the `python` tool (this hook builds a 3.14 .venv
# instead), so no `python` shim is generated and a bare `python` in
# an agent's shell falls through to the image's /usr/local/bin/python 3.11. That
# reads as a repo bug the moment it meets 3.14-only syntax — PEP 758's
# unparenthesized `except A, B:` in scripts/impeccable_lint.py raises SyntaxError
# there, and "fixing" it fights Black, which normalizes back to it under 3.14.
# Same trap for black/pytest/mypy: the ~/.local/bin copies are plugin-less.
# The directory need not exist yet — `mise install` below creates it, and PATH
# is only resolved once the agent runs a command.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  # ~/.local/bin carries the container image's user-level binaries.
  echo "export PATH=\"$HOME/.local/share/mise/shims:$CLAUDE_PROJECT_DIR/.venv/bin:$HOME/.local/bin:\$PATH\"" \
    >> "$CLAUDE_ENV_FILE"
  echo "export MISE_ENV=sandbox" >> "$CLAUDE_ENV_FILE"
fi

# Some sandbox images ship without mise. The standalone installer at mise.run
# is reachable through the egress proxy (unlike GitHub releases), so grab it
# from there; everything below assumes `mise` resolves.
if ! command -v mise > /dev/null 2>&1; then
  curl -fsSL https://mise.run | MISE_INSTALL_PATH="$HOME/.local/bin/mise" sh \
    || echo "WARN: mise self-install failed; most tooling below will be unavailable"
fi

# pipx serves the pipx: backends (poetry, shellcheck, hadolint) and runs uv
# below. It is in Ubuntu's own archive.
if ! command -v pipx > /dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  # --allow-releaseinfo-change: image PPAs occasionally change their metadata
  # (e.g. ondrej/php renamed its Label), which otherwise fails the update.
  { apt-get update -q --allow-releaseinfo-change > /dev/null \
    && apt-get install -y -q pipx > /dev/null; } \
    || echo "WARN: apt-get install pipx failed; pipx: tools will be unavailable"
fi

# ./.venv on Python 3.14. mise.sandbox.toml disables the mise-managed python,
# and images ship 3.10-3.13 with no deadsnakes PPA (seen 2026-10), so uv
# builds the venv: it takes a python3.14 already on PATH, or fetches the
# python-build-standalone build mise uses on laptops, and needs no ensurepip
# (Debian packages that apart as python3.14-venv). A fresh uv from PyPI, not
# the image's, which predates 3.14.0 and resolves `3.14` to an rc Poetry
# rejects. Poetry can't be left to it: it finds python3.14, then virtualenv
# builds the venv from the image's 3.11 anyway. A venv on another version,
# left by such a run, is rebuilt; Poetry then installs into it (poetry.toml).
if ! .venv/bin/python -c 'import sys; sys.exit(sys.version_info[:2] != (3, 14))' \
  > /dev/null 2>&1; then
  rm -rf .venv
  pipx run uv venv --python 3.14 --seed .venv > /dev/null \
    || echo "WARN: could not build a Python 3.14 .venv; the Python toolchain will be unavailable"
fi

# GNU gettext (msguniq) is what `mise run messages` shells out to; the image
# ships only pygettext3. Guarded on its own so an image that already has
# python3.14 and pipx still gets it.
if ! command -v msguniq > /dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  { apt-get update -q --allow-releaseinfo-change > /dev/null \
    && apt-get install -y -q gettext > /dev/null; } \
    || echo "WARN: apt-get install gettext failed; mise run messages will not extract strings"
fi

# Installs are best-effort: a blocked dependency (e.g. a registry trust gate)
# must not abort the whole hook. Warn and continue so the rest of the session
# setup still runs.
mise trust || echo "WARN: 'mise trust' failed"
mise install || echo "WARN: 'mise install' failed; some tools may be unavailable"

# The sandbox image pre-bakes GitHub-layout installs of some aliased tools
# (shellcheck, actionlint, hadolint at last check). mise then skips installing
# them, but their on-disk layout doesn't match the [tool_alias] backend, so
# mise can't list their bin paths: no shims are generated and `mise run` tasks
# drop them from PATH (hk dies with "actionlint: not found"). A missing shim
# is the reliable symptom — purge the clashing install and re-run
# `mise install` so the alias backend re-provisions it. Pre-baked installs
# whose layout happens to satisfy the alias (hk) keep their shim and are left
# alone, avoiding a pointless cargo rebuild.
purged=""
while IFS= read -r tool; do
  if [ ! -e "$HOME/.local/share/mise/shims/$tool" ]; then
    rm -rf "$HOME/.local/share/mise/installs/$tool"
    purged="$purged $tool"
  fi
done < <(sed -n '/^\[tool_alias\]/,/^\[/s/^\([a-zA-Z0-9_-]\{1,\}\)[[:space:]]*=.*/\1/p' \
  mise.sandbox.toml)
if [ -n "$purged" ]; then
  echo "Re-provisioning aliased tools with missing shims:$purged"
  mise install \
    || echo "WARN: 'mise install' retry failed; broken tools:$purged"
fi

mise bootstrap packages apply --yes || echo "WARN: 'mise bootstrap packages apply' failed"
mise run bootstrap || echo "WARN: 'mise run bootstrap' failed; JS deps/build may be unavailable"

# `mise run bootstrap` already runs `hk install --mise`, but only after
# poetry/aube installs that can fail in restricted sandboxes. Git hooks must be
# installed in every session regardless, so install them explicitly too
# (idempotent — hk rewrites .git/hooks in place).
mise exec -- hk install --mise || echo "WARN: 'hk install' failed; git hooks not installed"

# Playwright backs the e2e suite and `aubx agent-browser` screenshots; both
# share the Chromium it provisions. The image pre-bakes /opt/pw-browsers, but it
# lags whenever @playwright/test moves, and the pinned build is the only one
# Playwright will launch — so this step is load-bearing, not a no-op.
#
# The fallback fires on any non-zero exit from the task, not just the one that
# prompted it: `--with-deps` needs apt, which breaks whenever an image PPA
# changes its metadata. Don't fall back to one bare `playwright install` — it
# downloads the browsers in a single sequential loop and rethrows the first
# failure, so one unreachable artifact skips every browser queued behind it. Per
# browser, a failure is isolated and named. Missing OS libs are not the concern
# — the image ships no WebKit libs, but the host check is caught and printed as
# a warning, so the install still exits 0. The Playwright CDN itself is
# reachable through the egress proxy.
#
# `aube install` is retried first: the task runs it before the browser step, so
# `if !` also fires when node deps are what failed, and the per-browser task
# without them would warn three times for the wrong reason.
if ! mise run test:e2e:install; then
  mise exec -- aube install || echo "WARN: 'aube install' failed; e2e node deps missing"
  for browser in chromium firefox webkit; do
    mise run test:e2e:install:browser "$browser" \
      || echo "WARN: Playwright $browser unavailable; specs on it will fail"
  done
fi
