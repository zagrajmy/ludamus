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

# Playwright (needed by the e2e suite) also backs `aubx agent-browser`
# screenshots: agent-browser's own Chrome installer hits a network-blocked CDN,
# but it auto-discovers Playwright's Chromium via $PLAYWRIGHT_BROWSERS_PATH.
# Provision via the canonical task so e2e and screenshots both work out of the box.
mise run install:playwright \
  || echo "WARN: Playwright install failed; agent-browser screenshots unavailable"

# Self-check: surface screenshot-tooling readiness early rather than at capture
# time (see issue #379). Look for an actual executable Chrome, not just a
# directory, so a half-finished install doesn't falsely report ready.
browser_root="${PLAYWRIGHT_BROWSERS_PATH:-$HOME/.cache/ms-playwright}"
chrome_bin=$(find "$browser_root" -maxdepth 3 -type f -name chrome -perm -u+x 2>/dev/null | head -n1 || true)
if command -v aubx >/dev/null 2>&1 && [ -n "$chrome_bin" ]; then
  echo "OK: screenshots ready (aubx agent-browser + Chromium)"
else
  echo "WARN: screenshot tooling incomplete (aubx or Chromium missing); see CLAUDE.md"
fi

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
