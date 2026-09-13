---
title: 'Sandbox-only auth and modal E2E failures cascade into skipped tests'
severity: 'minor'
context:
  recorded_on: '2026-08-21'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 310
issue: 'zagrajmy/ludamus#1223'
---

## Expected Behavior

## Current Behavior

Full local e2e in the web sandbox: 15 auth/panel specs + the anonymous-code
modal reopen test fail deterministically (86 more don't run), while CI passes
the same commits — sandbox env issue, not code; cost a bisect via origin/main
checkout of client files to prove it

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-21. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L310).

Historical observation; not reproduced as part of this migration.
