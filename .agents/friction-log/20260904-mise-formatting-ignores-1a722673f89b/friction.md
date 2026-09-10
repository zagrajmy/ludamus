---
title: 'Mise formatting ignores hk''s vendored-script exclusions'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 499
---

## Expected Behavior

## Current Behavior

mise run format:oxfmt globs **/*.mjs with no exclusions, so it restyles the ~90
vendored .claude/skills/impeccable scripts that hk.pkl deliberately excludes.
Ran format, then git add -A, and 31k lines of vendored churn landed in my PR —
enough to push it past CodeRabbit's 100-file review limit. The mise task should
mirror hk.pkl's exclude list.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L499).

Historical observation; not reproduced as part of this migration.
