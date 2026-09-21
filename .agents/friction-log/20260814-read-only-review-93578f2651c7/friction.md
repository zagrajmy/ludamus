---
title: 'Read-only review agents can erase concurrent shared-worktree edits'
severity: 'minor'
context:
  recorded_on: '2026-08-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 216
issue: 'zagrajmy/ludamus#1207'
---

## Expected Behavior

## Current Behavior

A read-only review subagent ran `git restore --worktree .` in the shared
worktree and erased concurrent parent edits; read-only delegation needs
isolated worktrees or enforced write guards.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L216).

Historical observation; not reproduced as part of this migration.
