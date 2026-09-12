---
title: 'PostgreSQL tests fail at setup when the local database is stopped'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 44
---

## Expected Behavior

## Current Behavior

Ran test:postgres for the new party-invite concurrency check; the task assumes
PostgreSQL is already running and all six marked tests failed at setup with
connection refused.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L44).

Historical observation; not reproduced as part of this migration.
