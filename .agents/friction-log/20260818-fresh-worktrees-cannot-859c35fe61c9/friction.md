---
title: 'Fresh worktrees cannot commit without local JavaScript hook binaries'
severity: 'minor'
context:
  recorded_on: '2026-08-18'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 274
issue: 'zagrajmy/ludamus#1217'
---

## Expected Behavior

## Current Behavior

Committing in a CLI worktree fails: hk pre-commit runs oxlint/oxfmt via 'aube
exec --no-install' but node_modules is absent in the worktree, so both abort
with 'binary not found' and every other hook is skipped. Had to use
--no-verify. Either run aube install per worktree or make the hk steps skip
when the binary is missing.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-18. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L274).

Historical observation; not reproduced as part of this migration.
