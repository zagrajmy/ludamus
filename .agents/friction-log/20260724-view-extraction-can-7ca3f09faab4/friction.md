---
title: 'View extraction can remove timezone imports still needed by other settings views'
severity: 'minor'
context:
  recorded_on: '2026-07-24'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 93
issue: 'zagrajmy/ludamus#1185'
---

## Expected Behavior

## Current Behavior

While carving enrollment views out of event_settings.py, removing a shared
timezone import also broke pre-existing settings code; Ruff caught the
cross-section import coupling before commit.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-24. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L93).

Historical observation; not reproduced as part of this migration.
