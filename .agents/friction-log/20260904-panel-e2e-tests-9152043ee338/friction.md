---
title: 'Panel e2e tests leave duplicate spaces across reruns'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 494
issue: 'zagrajmy/ludamus#1254'
---

## Expected Behavior

## Current Behavior

panel.spec.ts is not re-runnable against the dev e2e DB: 'duplicates a space',
'copies a space to another event' and the session-field test create records and
never remove them, so a second run hits strict-mode violations on duplicate
names. Re-run test:e2e:prep between local runs, or have those tests clean up
like cover-images now does.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L494).

Historical observation; not reproduced as part of this migration.
