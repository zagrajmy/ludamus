---
title: 'Oxfmt creates unrelated churn in tracked Impeccable scripts'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 472
---

## Expected Behavior

## Current Behavior

mise run format (oxfmt) rewrites the vendored
.claude/skills/impeccable/scripts/*.mjs|js files, which are tracked. A one-
file change turned into 90 files of formatter churn I had to stash out before
committing. Those paths should be in the oxfmt ignore list.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L472).

Historical observation; not reproduced as part of this migration.
