---
title: 'Unmatched zsh test-file glob aborts code searches'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 20
issue: 'zagrajmy/ludamus#1171'
---

## Expected Behavior

## Current Behavior

Used a `test_*party*` zsh glob while locating party history tests; no match
caused zsh to abort before rg. Use rg paths without shell globs.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L20).

Historical observation; not reproduced as part of this migration.
