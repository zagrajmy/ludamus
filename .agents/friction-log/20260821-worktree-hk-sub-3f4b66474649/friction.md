---
title: 'Worktree hk sub-hooks lose the manually supplied Poetry virtualenv PATH'
severity: 'minor'
context:
  recorded_on: '2026-08-21'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 317
---

## Expected Behavior

## Current Behavior

Fresh worktree at .claude/worktrees/: .venv is absent (write- permission denied
outside the shared checkout), so hk's pre-commit codespell step failed with
'command not found' even after prepending the poetry venv bin for git. Root
cause: PATH must be exported for the whole shell session before invoking git
commit, not just prefixed on the git commit line, since hk re- execs sub-hooks.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-21. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L317).

Historical observation; not reproduced as part of this migration.
