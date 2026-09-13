---
title: 'Fresh-worktree extraction needs secrets and browser checks can use old client builds'
severity: 'minor'
context:
  recorded_on: '2026-09-09'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 535
issue: 'zagrajmy/ludamus#1268'
---

## Expected Behavior

## Current Behavior

messages requires development secrets in a fresh worktree; using ENV=test
supplies the committed test configuration for catalog extraction. Browser tests
also need a rebuild after client edits; prep had captured an earlier revision.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-09. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L535).

Historical observation; not reproduced as part of this migration.
