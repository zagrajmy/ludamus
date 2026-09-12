---
title: 'Sandbox djlint CSS formatting lacks cssbeautifier'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 488
---

## Expected Behavior

## Current Behavior

mise run lint:djlint blew up with ModuleNotFoundError: cssbeautifier in a fresh
web sandbox; djlint's --format-css needs it. Ran djlint directly on the one
changed template instead.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L488).

Historical observation; not reproduced as part of this migration.
