---
title: 'Focused panel e2e runs omit auth and earlier-test prerequisites'
severity: 'minor'
context:
  recorded_on: '2026-09-09'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 564
issue: 'zagrajmy/ludamus#1267'
---

## Expected Behavior

## Current Behavior

Running a focused panel.spec.ts E2E grep skipped prerequisites: first the auth
state was absent, then a category name initialized by an earlier test stayed
empty. The failed run also left :8000 occupied before prep.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-09. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L564).

Historical observation; not reproduced as part of this migration.
