---
title: 'Client rebuild leaves a bare Django server serving deleted asset hashes'
severity: 'minor'
context:
  recorded_on: '2026-08-12'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 198
---

## Expected Behavior

## Current Behavior

Ran `vite build` while a hand-started `django runserver` was up, so the running
process kept serving the old hashed CSS filename the build had just deleted.
Pages rendered unstyled and a Playwright hover-opacity assertion failed as if
the CSS were missing — it was a 404. `mise run test:e2e:serve` watches the
manifest and bounces itself; a hand-rolled runserver doesn't, so restart it
after every client build.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-12. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L198).

Historical observation; not reproduced as part of this migration.
