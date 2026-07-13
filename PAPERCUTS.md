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
- 2026-07-13: 5 of 143 e2e tests fail in the remote sandbox but pass in CI
  (cover-images upload, panel-crud facilitator, panel settings rename, firefox
  proposal-delete-restore, firefox velvet-sound reload hang). Clean DB and
  --workers=1 do not help; form POSTs exceed the 10s expect timeout and firefox
  never fires load on /design/ reload. Environment-specific, predates the
  sandbox-parity PRs.
