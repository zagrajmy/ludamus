---
title: 'E2E silently reuses a server running stale code'
severity: 'minor'
context:
  recorded_on: '2026-08-31'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 445
---

## Expected Behavior

## Current Behavior

e2e reused an already-running :8000 server, so test:e2e ran against stale
Python/templates and a new assertion failed with 'element not found'; only
test:e2e:kill + rerun made it pass

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-31. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L445).

Historical observation; not reproduced as part of this migration.
