---
title: 'Guessed pytest class names select zero enrollment tests'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 32
issue: 'zagrajmy/ludamus#1164'
---

## Expected Behavior

## Current Behavior

Guessed the focused test belonged to TestSessionEnrollPage from its filename;
pytest collected zero because the actual class is TestDesiredStateRouting.
Locate node IDs before invoking focused tests.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L32).

Historical observation; not reproduced as part of this migration.
