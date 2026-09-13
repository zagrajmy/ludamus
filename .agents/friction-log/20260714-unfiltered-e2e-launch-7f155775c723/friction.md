---
title: 'Unfiltered E2E launch leaves Chromium bootstrap conflicts'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 41
issue: 'zagrajmy/ludamus#1170'
---

## Expected Behavior

## Current Behavior

Targeted Chromium could not launch after an accidentally unfiltered mise task
spawned five browsers; stale Playwright Chromium processes hit macOS
MachPortRendezvous bootstrap conflicts.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L41).

Historical observation; not reproduced as part of this migration.
