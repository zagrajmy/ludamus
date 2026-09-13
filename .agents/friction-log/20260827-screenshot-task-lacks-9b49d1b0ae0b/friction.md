---
title: 'Screenshot task lacks authenticated state and obscures the e2e database'
severity: 'minor'
context:
  recorded_on: '2026-08-27'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 406
issue: 'zagrajmy/ludamus#1240'
---

## Expected Behavior

## Current Behavior

mise run shots can't reach logged-in pages: agent-browser has no
cookie/storage-state flag, so screenshotting any manager-only page (e.g. the
accept-proposal screen) meant hand-rolling a Playwright script that loads
tests/e2e/.auth-state-superuser.json. Also spent a while confused that 'mise
run dj shell' talks to the dev DB while test:e2e:serve serves dev.e2e.sqlite3 —
the data I queried was not the data the page rendered.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-27. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L406).

Historical observation; not reproduced as part of this migration.
