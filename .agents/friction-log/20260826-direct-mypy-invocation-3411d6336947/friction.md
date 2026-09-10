---
title: 'Direct mypy invocation crashes because its Django plugin lacks the test environment'
severity: 'minor'
context:
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  occurrences:
    - recorded_on: '2026-08-26'
      source_line: 384
    - recorded_on: '2026-09-01'
      source_line: 448
---

## Expected Behavior

## Current Behavior

### 2026-08-26 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L384)

Running mypy directly (including with a file path) crashed while constructing
the Django plugin because it missed the task's .env.test environment; mise run
lint:mypy succeeded.

### 2026-09-01 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L448)

Running mypy directly on the touched POLCON scripts crashed while constructing
NewSemanalDjangoPlugin; `mise run lint:mypy` is the supported invocation
because it loads `.env.test` and supplies `SRC_PATHS`.

## Possible Solution

## Minimal Reproducible Example

## Context

Two historical observations of the same missing Django task environment, kept
in one report so they share a resolution. Not reproduced as part of this migration.
