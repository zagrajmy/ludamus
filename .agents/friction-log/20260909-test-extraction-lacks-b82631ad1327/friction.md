---
title: 'Test extraction lacks SUPPORT_EMAIL and fuzzy-matches unrelated translations'
severity: 'minor'
context:
  recorded_on: '2026-09-09'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 539
---

## Expected Behavior

## Current Behavior

ENV=test still lacked SUPPORT_EMAIL for varlock; supplied a test address to run
messages. Gettext fuzzy-matched new search labels to host copy, requiring
explicit Polish corrections.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-09. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L539).

Historical observation; not reproduced as part of this migration.
