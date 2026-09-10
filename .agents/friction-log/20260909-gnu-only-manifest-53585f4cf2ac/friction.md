---
title: 'GNU-only manifest watcher serves deleted asset hashes on macOS'
severity: 'minor'
context:
  recorded_on: '2026-09-09'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 542
---

## Expected Behavior

## Current Behavior

The e2e server watcher uses GNU stat -c, so on macOS it misses rebuilt
manifests and keeps serving stale asset names. Restarted the server explicitly
after rebuilding.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-09. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L542).

Historical observation; not reproduced as part of this migration.
