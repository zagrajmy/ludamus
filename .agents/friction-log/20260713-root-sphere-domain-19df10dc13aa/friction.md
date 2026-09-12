---
title: 'Root-sphere domain drift causes an unexplained 500'
severity: 'minor'
context:
  recorded_on: '2026-07-13'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 11
---

## Expected Behavior

## Current Behavior

dev DB root sphere domain drifted from ROOT_DOMAIN (localhost:8000) -> every
request 500s with NotFoundError in middlewares.py:40; error page gives no hint
which domain was looked up

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-13. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L11).

Historical observation; not reproduced as part of this migration.
