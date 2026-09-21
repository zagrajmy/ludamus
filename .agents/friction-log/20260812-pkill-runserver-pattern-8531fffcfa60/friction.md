---
title: 'pkill runserver pattern kills the invoking agent shell'
severity: 'minor'
context:
  recorded_on: '2026-08-12'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 194
issue: 'zagrajmy/ludamus#1204'
---

## Expected Behavior

## Current Behavior

`pkill -f "django runserver"` killed my own shell — the pattern matches the
tool's command line too, so the bash call died with exit 144 mid- script
(twice, once leaving a half-written file). Killing the dev server needs the pid
from `ps -eo pid,cmd | grep "[d]jango runserver"`.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-12. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L194).

Historical observation; not reproduced as part of this migration.
