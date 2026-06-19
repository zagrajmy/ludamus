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

# `aubx agent-browser` needs a Chromium. Its bundled installer pulls from
# googlechromelabs.github.io, which the remote network policy blocks, but
# Playwright's CDN is reachable — so provision Chromium that way. agent-browser
# auto-discovers it via $PLAYWRIGHT_BROWSERS_PATH / the Playwright cache.
aube exec -C tests/e2e playwright install chromium --with-deps \
  || echo "WARN: could not provision Chromium; agent-browser screenshots unavailable"

# Self-check: surface screenshot-tooling readiness early rather than at capture
# time (see issue #379).
browser_root="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
if command -v aubx >/dev/null 2>&1 \
  && ls "$browser_root"/chromium-* >/dev/null 2>&1; then
  echo "OK: screenshots ready — aubx agent-browser + Chromium provisioned"
else
  echo "WARN: screenshot tooling incomplete (aubx or Chromium missing); see CLAUDE.md"
fi

if ! grep -q '^## Commits$' CLAUDE.local.md 2>/dev/null; then
  # Credit whoever is driving this session, not Claude/Anthropic.
  human_email="${CLAUDE_CODE_USER_EMAIL:-}"
  if [ -n "$human_email" ]; then
    printf '@CLAUDE.md\n\n## Commits\n\nCo-author the human, not Claude/Anthropic. End commits with:\n\n    Co-authored-by: %s <%s>\n' \
      "${human_email%@*}" "$human_email" >> CLAUDE.local.md
  else
    printf '@CLAUDE.md\n\n## Commits\n\nCo-author the human driving this session, not Claude/Anthropic.\n' >> CLAUDE.local.md
  fi
fi
