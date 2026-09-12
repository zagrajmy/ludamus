---
title: 'Direct pytest reports misleading Django discovery errors without task secrets'
severity: 'minor'
context:
  recorded_on: '2026-09-09'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 567
---

## Expected Behavior

## Current Behavior

Running targeted pytest directly, then with `ENV=test`, failed because test
secrets come from the mise task's `.env.test` file; pytest-django misleadingly
reported that it could not find the Django project.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-09. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L567).

Historical observation; not reproduced as part of this migration.
