---
title: 'Raw makemessages causes catalog churn instead of canonical extraction'
severity: 'minor'
context:
  recorded_on: '2026-08-29'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 433
---

## Expected Behavior

## Current Behavior

Reached for 'mise run dj makemessages' to regenerate the Polish catalog;
CLAUDE.md names 'mise run messages-resolve' for conflicts but not 'mise run
messages' for extraction, so the raw command looked right. It rewrites every
location line and stamps POT-Creation-Date, producing a 6000-line diff and a
failing test_translation_catalog. 'mise run messages' gives a 10-line diff.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-29. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L433).

Historical observation; not reproduced as part of this migration.
