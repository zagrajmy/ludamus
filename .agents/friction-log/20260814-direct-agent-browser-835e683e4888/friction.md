---
title: 'Direct agent-browser screenshots fail when the output directory is absent'
severity: 'minor'
context:
  recorded_on: '2026-08-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 213
issue: 'zagrajmy/ludamus#1206'
---

## Expected Behavior

## Current Behavior

agent-browser screenshot failed when screenshots/ did not already exist; the
direct CLI does not create parent directories, unlike mise run shots.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L213).

Historical observation; not reproduced as part of this migration.
