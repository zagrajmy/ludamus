---
title: 'Heavy schedule E2E assertions time out under local machine contention'
severity: 'minor'
context:
  recorded_on: '2026-08-24'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 332
---

## Expected Behavior

## Current Behavior

mise run diff-cover went red on three e2e tests (event-schedule- views 'rooms
tab swaps the layout in', event-filters 'carries filters across the schedule
view switch'); all three pass on re-run (32/32 with --repeat- each=8, both
browsers) and GitHub CI was green on the same commit. The local suite times out
on the heaviest page's 10s assertions when the machine is busy, so a red gate
can mean 'another job was running', with nothing in the output saying so.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-24. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L332).

Historical observation; not reproduced as part of this migration.
