---
title: 'Translation extraction requires unrelated secrets through varlock'
severity: 'minor'
context:
  recorded_on: '2026-08-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 219
issue: 'zagrajmy/ludamus#1208'
---

## Expected Behavior

## Current Behavior

`mise run messages` failed twice because varlock required deployment/test-only
secrets (including SUPPORT_EMAIL) even though catalog extraction does not use
them; the task needs a safe local environment.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L219).

Historical observation; not reproduced as part of this migration.
