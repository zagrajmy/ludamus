---
title: 'E2E manifest watcher cannot detect rebuilds on macOS'
severity: 'minor'
context:
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  occurrences:
    - recorded_on: '2026-09-04'
      source_line: 480
    - recorded_on: '2026-09-08'
      source_line: 526
    - recorded_on: '2026-09-09'
      source_line: 542
---

## Expected Behavior

## Current Behavior

### 2026-09-04 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L480)

Rebuilt the Vite client while test:e2e:serve was running. The serve loop
watches the manifest with stat -c, which is GNU-only, so on macOS it never
restarts and keeps serving hashed asset URLs the rebuild just deleted.

### 2026-09-08 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L526)

test:e2e:serve uses GNU stat -c to detect rebuilt manifests; macOS stat fails,
so the server keeps stale asset paths after a rebuild. Restarted the owned test
server manually.

### 2026-09-09 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L542)

The e2e server watcher uses GNU stat -c, so on macOS it misses rebuilt
manifests and keeps serving stale asset names. Restarted the server explicitly
after rebuilding.

## Possible Solution

## Minimal Reproducible Example

## Context

Three historical observations of the same manifest-watcher defect, kept in one
report so they share a resolution. Not reproduced as part of this migration.
