---
title: 'macOS e2e server misses Vite manifest changes'
severity: 'minor'
context:
  recorded_on: '2026-09-08'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 526
---

## Expected Behavior

## Current Behavior

test:e2e:serve uses GNU stat -c to detect rebuilt manifests; macOS stat fails,
so the server keeps stale asset paths after a rebuild. Restarted the owned test
server manually.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-08. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L526).

Historical observation; not reproduced as part of this migration.
