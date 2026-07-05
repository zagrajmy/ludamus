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
fi

# Installs are best-effort: a blocked dependency (e.g. a registry trust gate)
# must not abort the whole hook. Warn and continue so the rest of the session
# setup still runs.
mise trust || echo "WARN: 'mise trust' failed"
mise install || echo "WARN: 'mise install' failed; some tools may be unavailable"
mise bootstrap packages apply --yes || echo "WARN: 'mise bootstrap packages apply' failed"
mise run bootstrap || echo "WARN: 'mise run bootstrap' failed; JS deps/build may be unavailable"

# Playwright backs the e2e suite and `aubx agent-browser` screenshots; both
# share the Chromium it provisions.
mise run test:e2e:install \
  || echo "WARN: Playwright install failed; e2e suite and agent-browser screenshots unavailable"
