---
title: 'Global silence hook strips existing comments during unrelated edits'
severity: 'minor'
context:
  recorded_on: '2026-08-15'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 222
issue: 'zagrajmy/ludamus#1209'
---

## Expected Behavior

## Current Behavior

The global 'silence hook' PostToolUse hook on Write|Edit strips every
non-preserved comment from the whole file, not just newly added lines. Any
agent editing e.g. mills/timetable.py silently wipes its 76 explanatory
comments; 108 were lost across one branch before anyone noticed. Bash-driven
rewrites bypass it.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-15. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L222).

Historical observation; not reproduced as part of this migration.
