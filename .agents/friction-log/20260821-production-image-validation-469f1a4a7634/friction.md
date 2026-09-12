---
title: 'Production-image validation fails when the local Docker daemon is stopped'
severity: 'minor'
context:
  recorded_on: '2026-08-21'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 314
---

## Expected Behavior

## Current Behavior

Running the production-image validation initially failed because the Docker
daemon was unavailable; I had to start OrbStack manually before the build could
run.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-21. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L314).

Historical observation; not reproduced as part of this migration.
