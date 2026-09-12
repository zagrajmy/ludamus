---
title: 'Local lint omits translation freshness checks required by CI'
severity: 'minor'
context:
  recorded_on: '2026-09-06'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 511
issue: 'zagrajmy/ludamus#1259'
---

## Expected Behavior

## Current Behavior

ran mise run lint before pushing and CI's checks job still failed on
messages-check; lint does not include it, only pr-fix does, so a stale
django.po only shows up on CI

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-06. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L511).

Historical observation; not reproduced as part of this migration.
