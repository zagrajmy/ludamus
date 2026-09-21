---
title: 'Python patch upgrades leave virtualenv console scripts pointing at a deleted interpreter'
severity: 'minor'
context:
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  occurrences:
    - recorded_on: '2026-08-16'
      source_line: 240
    - recorded_on: '2026-08-16'
      source_line: 258
issue: 'zagrajmy/ludamus#1213'
---

## Expected Behavior

## Current Behavior

### 2026-08-16 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L240)

every mise task died with '<tool>: not found' (pytest, mypy, pylint)
mid-session. Cause: mise replaced python 3.14.6 with 3.14.7 and deleted the old
install, leaving .venv/bin/python dangling, so every console script's shebang
ENOENT'd. Only the shebang-less native binaries (ruff, taplo) kept working, and
pylint's one half-run reported E0401 on stdlib imports — both misleading. mise
recreates .venv only when it is absent, never when its interpreter is stale;
repointing .venv/bin/python and pyvenv.cfg at the .../installs/python/3.14
alias instead of the patch dir survives the next bump.

### 2026-08-16 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L258)

mise run test:py failed with 'sh: 1: pytest: not found' after mise pruned
python 3.14.6: .venv/bin/python was a dangling symlink into the removed
install, so mise silently skipped venv activation for tasks (mise x still
resolved it). Repointed .venv/bin/python + pyvenv.cfg at 3.14 by hand. mise run
should say the venv is unusable instead of running the task without it.

## Possible Solution

## Minimal Reproducible Example

## Context

Two historical observations of the same dangling-interpreter defect, kept in one
report so they share a resolution. Not reproduced as part of this migration.
