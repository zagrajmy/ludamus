---
title: 'Direct pytest invocation fails late when the Django ENV setting is missing'
severity: 'minor'
context:
  recorded_on: '2026-08-21'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 323
---

## Expected Behavior

## Current Behavior

Running focused pytest directly from a worktree failed because ENV was unset;
the traceback only later explained pytest-django could not initialize. Use mise
run test:int -- PATH so the task supplies the test environment.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-21. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L323).

Historical observation; not reproduced as part of this migration.
