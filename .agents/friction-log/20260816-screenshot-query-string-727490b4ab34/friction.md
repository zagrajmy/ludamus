---
title: 'Screenshot query-string quoting fix still leaves Chrome sandbox failures'
severity: 'minor'
context:
  recorded_on: '2026-08-16'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 254
---

## Expected Behavior

## Current Behavior

mise run shots breaks on URLs with a query string: mise quotes the arg, so the
task builds http://localhost:8000'/path/?view=rooms' and curl reports it
unreachable. Had to call aubx agent-browser directly (which then failed on
Chrome's sandbox).

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-16. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L254).

Historical observation; not reproduced as part of this migration.
