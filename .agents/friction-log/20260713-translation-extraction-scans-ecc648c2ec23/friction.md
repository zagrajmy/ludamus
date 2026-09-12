---
title: 'Translation extraction scans nested worktree checkouts'
severity: 'minor'
context:
  recorded_on: '2026-07-13'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 14
---

## Expected Behavior

## Current Behavior

`mise run messages` still scans top-level `worktrees/`, mixing strings and
source references from sibling checkouts into the catalog and sometimes finding
duplicate POT definitions. Run extraction from a checkout with no nested
worktrees until the task excludes them.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-13. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L14).

Historical observation; not reproduced as part of this migration.
