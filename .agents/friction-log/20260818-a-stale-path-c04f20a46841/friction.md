---
title: 'A stale PATH-selected tingle rejects the project''s regex_spread metric'
severity: 'minor'
context:
  recorded_on: '2026-08-18'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 279
issue: 'zagrajmy/ludamus#1216'
---

## Expected Behavior

## Current Behavior

mise run lint:tingle failed with 'unknown type regex_spread' because a stale
tingle resolved ahead of the project venv on PATH; running .venv/bin/tingle
check directly worked.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-18. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L279).

Historical observation; not reproduced as part of this migration.
