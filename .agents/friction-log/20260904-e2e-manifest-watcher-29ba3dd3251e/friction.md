---
title: 'E2E manifest watcher cannot detect rebuilds on macOS'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 480
---

## Expected Behavior

## Current Behavior

Rebuilt the Vite client while test:e2e:serve was running. The serve loop
watches the manifest with stat -c, which is GNU-only, so on macOS it never
restarts and keeps serving hashed asset URLs the rebuild just deleted.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L480).

Historical observation; not reproduced as part of this migration.
