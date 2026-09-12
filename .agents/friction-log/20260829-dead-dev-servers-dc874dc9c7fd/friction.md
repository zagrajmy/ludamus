---
title: 'Dead dev servers leave stale portless routes and unsafe cleanup'
severity: 'minor'
context:
  recorded_on: '2026-08-29'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 426
---

## Expected Behavior

## Current Behavior

mise run start leaves a portless proxy on :1355 behind when the dev server dies
(e.g. after test:e2e kills :8000). The next start binds a new app port but the
stale proxy keeps forwarding to the dead one, so every URL 404s with a page
that still contains an h2 — readiness greps pass and Playwright then fails deep
in a script. Had to pkill -f portless between runs, and pkill -f portless
matches the invoking shell's own command line, killing it (exit 144).

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-29. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L426).

Historical observation; not reproduced as part of this migration.
