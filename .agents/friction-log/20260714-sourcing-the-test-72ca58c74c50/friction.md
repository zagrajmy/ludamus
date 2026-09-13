---
title: 'Sourcing the test environment does not configure standalone Django'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 35
issue: 'zagrajmy/ludamus#1169'
---

## Expected Behavior

## Current Behavior

Ran a standalone Django metadata check after sourcing .env.test;
DJANGO_SETTINGS_MODULE was still unset, so setup failed before printing the
table name.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L35).

Historical observation; not reproduced as part of this migration.
