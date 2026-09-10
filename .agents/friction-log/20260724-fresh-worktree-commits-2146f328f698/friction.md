---
title: 'Fresh worktree commits fail until their mise configuration is trusted'
severity: 'minor'
context:
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  occurrences:
    - recorded_on: '2026-07-24'
      source_line: 80
    - recorded_on: '2026-09-01'
      source_line: 451
---

## Expected Behavior

## Current Behavior

### 2026-07-24 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L80)

Committed from a new git worktree → hook startup failed because the copied
mise.toml was untrusted; trust was required before hooks could run.

### 2026-09-01 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L451)

Committing from a fresh git worktree triggered hooks before mise trusted that
worktree’s identical mise.toml; the commit failed until the duplicate config
was trusted.

## Possible Solution

## Minimal Reproducible Example

## Context

Two historical observations of the same worktree-trust requirement, kept in one
report so they share a resolution. Not reproduced as part of this migration.
