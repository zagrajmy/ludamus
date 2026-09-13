---
title: 'Local Playwright silently reuses stale no-reload Django servers'
severity: 'minor'
context:
  recorded_on: '2026-08-20'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 304
issue: 'zagrajmy/ludamus#1220'
---

## Expected Behavior

## Current Behavior

Playwright's reuseExistingServer:!isCI silently reused a stale `django-admin
runserver --noreload` I had left on :8000 for screenshots, so `mise run
test:e2e` tested pre-edit Python and failed on an assertion that was actually
correct. Took a while to spot because the failure looked like a real
regression. A note in the e2e docs, or a staleness check on the reused server,
would have saved it.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-20. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L304).

Historical observation; not reproduced as part of this migration.
