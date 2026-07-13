# Papercuts

Small friction hit while working — retried tool calls, confusing setup steps,
flaky commands, stale caches, misleading errors, non-obvious gotchas. One or two
sentences each: what you were doing → what got in the way. See CLAUDE.md.

<!-- Append new entries below, newest last. -->
- 2026-07-10: session-start hook's `playwright install --with-deps` fails in
  fresh sandboxes: apt-get update exits 100 because the image's ondrej/php PPA
  changed its InRelease Label. Browsers are preinstalled at /opt/pw-browsers so
  the failure is soft, but the WARN is misleading.
- 2026-07-10: `mise run papercut -- <note>` garbles apostrophes in the note
  (writes literal `'\''` sequences into PAPERCUTS.md) and doesn't wrap at 80
  columns, so the very next commit trips markdownlint MD013 on the file it
  just wrote. Fixed: the task now shlex-unquotes the note and wraps entries
  at 80 columns.
- 2026-07-10: fresh sandbox: `mise run check` failed with actionlint/hadolint
  not found. The image pre-bakes GitHub-layout installs of aliased tools; mise
  then skips installing them but cannot list their bin paths, so no shims and
  no task PATH entries. Fixed by purging installs without shims and rerunning
  `mise install` in the session-start hook.
- 2026-07-10: the pre-baked /opt/pw-browsers chromium build (1194) does not
  match @playwright/test 1.58.2 (needs 1208), so e2e cannot launch a browser
  and the preinstalled-browsers fallback is not real. Plain
  `playwright install` without `--with-deps` works through the proxy.
- 2026-07-13: aube install via mise fails for ~7 days after a release: ~/.npmrc
  min-release-age=7 blocks the darwin-arm64 platform package; one-shot fix
  npm_config_min_release_age=0 mise install npm:@endevco/aube
- 2026-07-13: dev DB root sphere domain drifted from ROOT_DOMAIN
  (localhost:8000) -> every request 500s with NotFoundError in
  middlewares.py:40; error page gives no hint which domain was looked up
