---
title: 'Focused test execution falls back to direct pytest without the required test environment'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 371
---

## Expected Behavior

## Current Behavior

Passing paths after 'mise run test:py --' was ignored because the task
hardcodes both test trees, so a targeted check unexpectedly ran all 4,600
tests; direct pytest then lacked the task's .env.test environment.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L371).

Historical observation; not reproduced as part of this migration.
