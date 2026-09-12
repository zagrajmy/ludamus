---
title: 'mypy incremental cache invents a protocol incompatibility after a NewType change'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 361
issue: 'zagrajmy/ludamus#1231'
---

## Expected Behavior

## Current Behavior

mypy's incremental cache invented a phantom protocol conflict after a NewType
change: inits/middleware.py reported Services not matching ServicesProtocol
while an explicit assignment of the same two classes type- checked fine. rm -rf
.mypy_cache made it vanish.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L361).

Historical observation; not reproduced as part of this migration.
