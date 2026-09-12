---
title: 'Parallel message extraction and formatting race over temporary template Python files'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 378
---

## Expected Behavior

## Current Behavior

Running messages-check in parallel with mise check raced makemessages'
temporary *.html.py extraction files against Black, causing 255 template parse
errors; these tasks must run sequentially.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L378).

Historical observation; not reproduced as part of this migration.
