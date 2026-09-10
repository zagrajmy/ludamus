---
title: 'djlint reformat reports zero lint errors but returns a failing exit status'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 365
---

## Expected Behavior

## Current Behavior

Ran format:djlint on a template change; it reformatted the file and reported
zero lint errors but still exited nonzero, so the formatting task appeared to
fail until rerun.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L365).

Historical observation; not reproduced as part of this migration.
