---
title: 'Direct mypy invocation crashes because its Django plugin lacks the test environment'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 384
---

## Expected Behavior

## Current Behavior

Running mypy directly (including with a file path) crashed while constructing
the Django plugin because it missed the task's .env.test environment; mise run
lint:mypy succeeded.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L384).

Historical observation; not reproduced as part of this migration.
