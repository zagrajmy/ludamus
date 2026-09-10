---
title: 'E2E formatting cannot resolve oxfmt locally and djlint exits after reformatting'
severity: 'minor'
context:
  recorded_on: '2026-07-23'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 58
---

## Expected Behavior

## Current Behavior

Formatting the Playwright test with aube exec -C tests/e2e failed because oxfmt
is only available from the repository toolchain; running it from the repository
root worked. format:djlint also exits nonzero after successfully reformatting a
file, requiring a second pass.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-23. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L58).

Historical observation; not reproduced as part of this migration.
