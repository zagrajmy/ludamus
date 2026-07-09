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

# Put mise-managed tool shims (aubx -> agent-browser, ast-grep, poetry, node,
# python, markdownlint-cli2, ...) on PATH for every shell in the session, so
# tools resolve directly instead of needing `mise exec`/activation per command.
# Persisted for the session via CLAUDE_ENV_FILE.
#
# PREPEND, don't append: mise inserts its managed paths (incl. the .venv
# activation from `_.python.venv`) at the shims' position in PATH. Appended
# shims put the venv after the container's bare /usr/local/bin/python, and
# every `mise run` task fails with "No module named 'django'".
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"$HOME/.local/share/mise/shims:\$PATH\"" >> "$CLAUDE_ENV_FILE"
  # ~/.local/bin carries fallback binaries vendored below (e.g. shellcheck).
  echo "export PATH=\"$HOME/.local/bin:\$PATH\"" >> "$CLAUDE_ENV_FILE"
fi

# Installs are best-effort: a blocked dependency (e.g. a registry trust gate)
# must not abort the whole hook. Warn and continue so the rest of the session
# setup still runs.
mise trust || echo "WARN: 'mise trust' failed"
mise install || echo "WARN: 'mise install' failed; some tools may be unavailable"

# GitHub-release-backed tools cannot download through the sandbox egress
# proxy, and one failed [tools] install wedges every subsequent `mise run`.
# Disable exactly the tools whose install failed; scripts/sandbox-bootstrap
# below re-provides each of them from a reachable registry via the
# gitignored .mise.local.toml.
missing="$(MISE_DISABLE_TOOLS='' mise ls --current --json 2>/dev/null | python3 -c '
import json, sys
data = json.load(sys.stdin)
print(",".join(
    name for name, versions in data.items()
    if not any(v.get("installed") for v in versions)
))' || true)"
if [ -n "$missing" ]; then
  echo "WARN: disabling uninstallable mise tools: $missing"
  mise settings set disable_tools "$missing" \
    || echo "WARN: could not persist disable_tools"
fi
# scripts/sandbox-bootstrap substitutes every blocked tool from a reachable
# host (apt python, cargo hk, PyPI wheels, Go module proxy — see the script
# header); idempotent, per-step best-effort, no-op where the normal tools
# already work. See docs/agents/sandbox.md.
bash scripts/sandbox-bootstrap || echo "WARN: sandbox-bootstrap failed"

mise bootstrap packages apply --yes || echo "WARN: 'mise bootstrap packages apply' failed"
mise run bootstrap || echo "WARN: 'mise run bootstrap' failed; JS deps/build may be unavailable"

# `mise run bootstrap` already runs `hk install --mise`, but only after
# poetry/aube installs that can fail in restricted sandboxes. Git hooks must be
# installed in every session regardless, so install them explicitly too
# (idempotent — hk rewrites .git/hooks in place).
mise exec -- hk install --mise || echo "WARN: 'hk install' failed; git hooks not installed"

# Playwright backs the e2e suite and `aubx agent-browser` screenshots; both
# share the Chromium it provisions.
mise run test:e2e:install \
  || echo "WARN: Playwright install failed; e2e suite and agent-browser screenshots unavailable"
