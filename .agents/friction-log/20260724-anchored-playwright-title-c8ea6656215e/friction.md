---
title: 'Anchored Playwright title filters match zero tests without showing full titles'
severity: 'minor'
context:
  recorded_on: '2026-07-24'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 70
---

## Expected Behavior

## Current Behavior

Running a focused E2E via mise run test:e2e with an anchored suite/title grep
matched zero tests; Playwright output did not reveal the actual full title.
Retried with the unique test-name substring.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-24. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L70).

Historical observation; not reproduced as part of this migration.
