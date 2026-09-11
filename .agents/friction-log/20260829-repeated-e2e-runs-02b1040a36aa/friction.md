---
title: 'Repeated e2e runs reuse mutated bookmark and fixture state'
severity: 'minor'
context:
  recorded_on: '2026-08-29'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 439
---

## Expected Behavior

## Current Behavior

Ran 'mise run test:e2e' twice in a session without re-running 'test:e2e:prep'
between. The second run failed event-schedule- views.spec.ts:655 (overnight
bookmark) because that test mutates bookmark state the first run had already
toggled — it looks like a code regression, and cost a round of ruling out an
unrelated diff. Re-prep before a second full run, or the suite is only
trustworthy once per seed.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-29. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L439).

Historical observation; not reproduced as part of this migration.
