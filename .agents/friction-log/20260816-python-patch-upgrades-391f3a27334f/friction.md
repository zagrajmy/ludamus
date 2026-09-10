---
title: 'Python patch upgrades leave virtualenv console scripts pointing at a deleted interpreter'
severity: 'minor'
context:
  recorded_on: '2026-08-16'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 240
---

## Expected Behavior

## Current Behavior

every mise task died with '<tool>: not found' (pytest, mypy, pylint)
mid-session. Cause: mise replaced python 3.14.6 with 3.14.7 and deleted the old
install, leaving .venv/bin/python dangling, so every console script's shebang
ENOENT'd. Only the shebang-less native binaries (ruff, taplo) kept working, and
pylint's one half-run reported E0401 on stdlib imports — both misleading. mise
recreates .venv only when it is absent, never when its interpreter is stale;
repointing .venv/bin/python and pyvenv.cfg at the .../installs/python/3.14
alias instead of the patch dir survives the next bump.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-16. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L240).

Historical observation; not reproduced as part of this migration.
