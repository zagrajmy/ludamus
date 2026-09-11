---
title: 'System Python tools shadow the project virtualenv inside mise tasks'
severity: 'minor'
context:
  recorded_on: '2026-07-31'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 121
---

## Expected Behavior

## Current Behavior

every mise task resolves its Python tool from PATH, so any shell that puts
~/.local/bin ahead of the mise shims gets the image's uv-installed
pytest/mypy/black instead of .venv's. 'mise run test:py' then dies with
ModuleNotFoundError: No module named 'django'. Took a while to spot because the
traceback points at tests/conftest.py, not at the wrong interpreter.
session-start.sh orders PATH correctly; nothing enforces it elsewhere.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-31. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L121).

Historical observation; not reproduced as part of this migration.
