---
title: 'Fresh worktree commits fail until their mise configuration is trusted'
severity: 'minor'
context:
  recorded_on: '2026-07-24'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 80
---

## Expected Behavior

## Current Behavior

Committed from a new git worktree → hook startup failed because the copied
mise.toml was untrusted; trust was required before hooks could run.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-24. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L80).

Historical observation; not reproduced as part of this migration.
