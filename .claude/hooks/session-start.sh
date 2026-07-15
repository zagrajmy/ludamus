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
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  # ~/.local/bin carries the container image's user-level binaries.
  echo "export PATH=\"$HOME/.local/share/mise/shims:$HOME/.local/bin:\$PATH\"" \
    >> "$CLAUDE_ENV_FILE"
  echo "export MISE_ENV=sandbox" >> "$CLAUDE_ENV_FILE"
fi

# python3.14 and pipx come from apt: mise.sandbox.toml disables the (blocked)
# mise-managed python, the sandbox image preconfigures the deadsnakes PPA, and
# `_.python.venv` then creates .venv from this interpreter. pipx serves the
# pipx: backends (poetry, shellcheck, hadolint).
if ! command -v python3.14 > /dev/null 2>&1 \
  || ! command -v pipx > /dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  # --allow-releaseinfo-change: image PPAs occasionally change their metadata
  # (e.g. ondrej/php renamed its Label), which otherwise fails the update.
  apt-get update -q --allow-releaseinfo-change > /dev/null \
    || echo "WARN: apt-get update failed"
  apt-get install -y -q python3.14 python3.14-venv pipx > /dev/null \
    || echo "WARN: apt-get install python3.14/pipx failed; Python tooling may be unavailable"
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
# share the Chromium it provisions. The task's `--with-deps` needs apt, which
# breaks whenever an image PPA changes its metadata; the image already ships
# every OS lib Chromium needs, so fall back to a dependency-less browser
# download (the Playwright CDN is reachable through the egress proxy).
mise run test:e2e:install \
  || mise exec -- aube exec -C tests/e2e playwright install \
  || echo "WARN: Playwright install failed; e2e suite and agent-browser screenshots unavailable"
