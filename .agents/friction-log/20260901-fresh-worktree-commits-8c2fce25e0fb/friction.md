---
title: 'Fresh worktree commits fail before mise configuration is trusted'
severity: 'minor'
context:
  recorded_on: '2026-09-01'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 451
---

## Expected Behavior

## Current Behavior

Committing from a fresh git worktree triggered hooks before mise trusted that
worktree’s identical mise.toml; the commit failed until the duplicate config
was trusted.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-01. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L451).

Historical observation; not reproduced as part of this migration.
