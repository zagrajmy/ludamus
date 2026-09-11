---
title: 'Concurrent worktrees collide on the shared e2e port'
severity: 'minor'
context:
  recorded_on: '2026-09-09'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 545
---

## Expected Behavior

## Current Behavior

Another worktree took over port 8000 while this browser run and server were
killed (exit 137). Moved this worktree to port 8017 and reran against an
explicit E2E_BASE_URL to isolate verification.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-09. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L545).

Historical observation; not reproduced as part of this migration.
