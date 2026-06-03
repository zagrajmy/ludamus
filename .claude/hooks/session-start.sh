#!/bin/bash
set -euo pipefail

# Only run in Claude Code on the web (remote) environments.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

# Run setup in the background so the session starts immediately — Claude
# usually reads files and talks before it needs the toolchain.
echo '{"async": true, "asyncTimeout": 600000}'

cd "$CLAUDE_PROJECT_DIR"

export PATH="$HOME/.local/bin:$PATH"

# mise manages Python, Node, Poetry, ast-grep, aube, markdownlint.
mise trust
mise install

# Idempotent dev setup: poetry + aube deps, .env.local, migrations,
# vendored static, demo data.
mise run bootstrap
