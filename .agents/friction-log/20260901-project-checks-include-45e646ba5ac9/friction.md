---
title: 'Project checks include untracked Pi agent-state JSON'
severity: 'minor'
context:
  recorded_on: '2026-09-01'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 461
---

## Expected Behavior

## Current Behavior

Running mise run check inspected the untracked .pi agent-state directory and
failed on a generated JSON file missing a final newline, so project checks
require moving unrelated harness state aside.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-01. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L461).

Historical observation; not reproduced as part of this migration.
