---
title: 'Direct mypy invocation crashes without the task environment'
severity: 'minor'
context:
  recorded_on: '2026-09-01'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 448
---

## Expected Behavior

## Current Behavior

Running mypy directly on the touched POLCON scripts crashed while constructing
NewSemanalDjangoPlugin; `mise run lint:mypy` is the supported invocation
because it loads `.env.test` and supplies `SRC_PATHS`.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-01. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L448).

Historical observation; not reproduced as part of this migration.
