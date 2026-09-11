---
title: 'Isolated browser verification requires manual domain changes and registry access'
severity: 'minor'
context:
  recorded_on: '2026-09-08'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 529
---

## Expected Behavior

## Current Behavior

Chip-color verification on an isolated port required updating the seeded
django_site domain. The e2e wrapper tried registry downloads despite installed
browser tools; used the installed Playwright runner directly.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-08. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L529).

Historical observation; not reproduced as part of this migration.
