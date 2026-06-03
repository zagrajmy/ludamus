#!/bin/bash
set -euo pipefail

# Only run in Claude Code on the web (remote) environments.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

export PATH="$HOME/.local/bin:$PATH"

# mise manages Python, Node, Poetry, ast-grep, aube, markdownlint.
mise trust
mise install

# Python deps into the mise-managed .venv, then frontend/workspace deps.
mise exec -- poetry install
mise exec -- aube install
