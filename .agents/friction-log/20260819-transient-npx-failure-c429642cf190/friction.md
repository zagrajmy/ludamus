---
title: 'Transient npx failure leaves the lint gate without the failed command or explanation'
severity: 'minor'
context:
  recorded_on: '2026-08-19'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 289
issue: 'zagrajmy/ludamus#1219'
---

## Expected Behavior

## Current Behavior

lint:impeccable failed the pr-fix gate with 'impeccable failed (exit 1):' and
both npx streams empty, so the gate output carried no diagnosis at all. The
task then passed on every re-run I could construct: warm cache, cold cache
(NPM_CONFIG_CACHE to a temp dir), CI=1, three concurrent npx invocations, and
the full 259-file tracked scan. scripts/impeccable_lint.py's failure path
prints only the exit code and the two (empty) streams, never the command, so a
transient npx death is unrepairable from what the gate says.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-19. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L289).

Historical observation; not reproduced as part of this migration.
