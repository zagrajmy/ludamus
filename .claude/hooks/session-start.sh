#!/bin/bash
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo '{"async": true, "asyncTimeout": 600000}'

cd "$CLAUDE_PROJECT_DIR"

export PATH="$HOME/.local/bin:$PATH"

# GNU gettext (msgfmt/msgmerge) backs the translation tasks.
if command -v apt-get >/dev/null 2>&1; then
  apt-get install -y gettext >/dev/null 2>&1 || true
fi

mise trust
mise install
mise run bootstrap
