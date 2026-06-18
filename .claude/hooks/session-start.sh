#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo '{"async": true, "asyncTimeout": 600000}'

cd "$CLAUDE_PROJECT_DIR"

export PATH="$HOME/.local/bin:$PATH"

# Put mise-managed tool shims (aubx -> agent-browser, ast-grep, poetry, node,
# python, markdownlint-cli2, ...) on PATH for every shell in the session, so
# tools resolve directly instead of needing `mise exec`/activation per command.
# Persisted for the session via CLAUDE_ENV_FILE.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo "export PATH=\"\$PATH:$HOME/.local/share/mise/shims\"" >> "$CLAUDE_ENV_FILE"
fi

# GNU gettext (msgfmt/msgmerge) backs the translation tasks.
if command -v apt-get >/dev/null 2>&1; then
  apt-get install -y gettext >/dev/null 2>&1 || true
fi

mise trust
mise install
mise run bootstrap

if ! grep -q '^## Commits$' CLAUDE.local.md 2>/dev/null; then
  printf '@CLAUDE.md\n\n## Commits\n\nAdd the human in Co-authored-by when committing\n' >> CLAUDE.local.md
fi
