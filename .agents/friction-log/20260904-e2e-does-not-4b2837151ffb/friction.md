---
title: 'E2E does not reject unrelated servers occupying port 8000'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 476
issue: 'zagrajmy/ludamus#1252'
---

## Expected Behavior

## Current Behavior

A stray 'mise run start' holding :8000 gets silently reused by mise run
test:e2e, which then tests stale code. The failure looks like a broken
selector, not a stale server. test:e2e should fail loudly (or kill) when :8000
is already taken by something it did not start.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L476).

Historical observation; not reproduced as part of this migration.
