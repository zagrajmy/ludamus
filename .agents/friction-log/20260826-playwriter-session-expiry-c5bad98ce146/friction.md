---
title: 'Playwriter session expiry interrupts subsequent UI verification passes'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 368
issue: 'zagrajmy/ludamus#1233'
---

## Expected Behavior

## Current Behavior

Playwriter session expired between UI verification passes, so the saved session
could not inspect the refreshed page; use a fresh browser session or the E2E
server instead.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L368).

Historical observation; not reproduced as part of this migration.
