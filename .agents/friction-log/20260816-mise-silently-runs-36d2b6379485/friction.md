---
title: 'mise silently runs tasks without a usable venv after Python pruning'
severity: 'minor'
context:
  recorded_on: '2026-08-16'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 258
---

## Expected Behavior

## Current Behavior

mise run test:py failed with 'sh: 1: pytest: not found' after mise pruned
python 3.14.6: .venv/bin/python was a dangling symlink into the removed
install, so mise silently skipped venv activation for tasks (mise x still
resolved it). Repointed .venv/bin/python + pyvenv.cfg at 3.14 by hand. mise run
should say the venv is unusable instead of running the task without it.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-16. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L258).

Historical observation; not reproduced as part of this migration.
