---
title: 'Local check omits the translation-freshness gate enforced in CI'
severity: 'minor'
context:
  recorded_on: '2026-07-27'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 104
---

## Expected Behavior

## Current Behavior

mise run check (format+lint) omits messages-check, so a stale PL catalog passes
locally and only fails in CI; after any edit that reorders translated strings,
run 'mise run messages-check' separately.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-27. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L104).

Historical observation; not reproduced as part of this migration.
