---
title: 'Sandbox djlint executable and regex dependency are missing'
severity: 'minor'
context:
  recorded_on: '2026-08-27'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 402
---

## Expected Behavior

## Current Behavior

mise run lint:djlint says 'djlint: not found' in a web sandbox, and the hk
pre-commit djlint check step dies with ModuleNotFoundError: No module named
'regex' (its reformat step right after works fine). Had to commit to find out
templates lint clean.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-27. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L402).

Historical observation; not reproduced as part of this migration.
