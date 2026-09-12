---
title: 'Formatting one template also rewrites unrelated dirty templates'
severity: 'minor'
context:
  recorded_on: '2026-07-23'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 62
---

## Expected Behavior

## Current Behavior

Running format:djlint for one navbar change reformatted an unrelated dirty
template, then exited nonzero. A scoped formatter/check target would avoid
disturbing concurrent work.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-23. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L62).

Historical observation; not reproduced as part of this migration.
