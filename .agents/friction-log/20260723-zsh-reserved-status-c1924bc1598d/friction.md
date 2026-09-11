---
title: 'Zsh reserved status variable breaks validation result capture'
severity: 'minor'
context:
  recorded_on: '2026-07-23'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 67
---

## Expected Behavior

## Current Behavior

Wrapped validation commands used zsh reserved variable status, so result
capture failed after the tasks completed; use a task-specific exit variable.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-23. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L67).

Historical observation; not reproduced as part of this migration.
