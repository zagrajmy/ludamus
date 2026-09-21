---
title: 'Fresh-worktree translation resolution and PR diff commands have hidden requirements'
severity: 'minor'
context:
  recorded_on: '2026-09-08'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 520
issue: 'zagrajmy/ludamus#1261'
---

## Expected Behavior

## Current Behavior

PR 723 restore: messages-resolve requires ENV=test in an unconfigured worktree;
default development config lacks secrets. gh pr diff has no --stat flag, use
git diff --stat.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-08. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L520).

Historical observation; not reproduced as part of this migration.
