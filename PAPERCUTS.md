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
  just wrote.
