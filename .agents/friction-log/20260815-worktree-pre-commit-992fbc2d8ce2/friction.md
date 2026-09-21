---
title: 'Worktree pre-commit hooks inherit an unusable main-checkout virtualenv PATH'
severity: 'minor'
context:
  recorded_on: '2026-08-15'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 232
issue: 'zagrajmy/ludamus#1210'
---

## Expected Behavior

## Current Behavior

git commit's hk pre-commit hook (djlint/codespell/yamllint) fails with 'not
found' in this worktree because the session PATH bakes in
/home/user/ludamus/.venv/bin from the main checkout, but that .venv doesn't
exist and I can't create it (write-permission denied outside my worktree).
Worked around by prepending the poetry-managed venv's bin dir to PATH for the
git commit invocation; poetry install must be run without mise exec (mise
exec's venv also resolves to the wrong checkout path) to get a usable venv at
all.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-15. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L232).

Historical observation; not reproduced as part of this migration.
