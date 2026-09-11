---
title: 'djlint reformat reports zero lint errors but returns a failing exit status'
severity: 'minor'
context:
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  occurrences:
    - recorded_on: '2026-08-26'
      source_line: 365
    - recorded_on: '2026-09-01'
      source_line: 458
---

## Expected Behavior

## Current Behavior

### 2026-08-26 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L365)

Ran format:djlint on a template change; it reformatted the file and reported
zero lint errors but still exited nonzero, so the formatting task appeared to
fail until rerun.

### 2026-09-01 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L458)

The format:djlint task reformatted the changed template successfully but still
exited 1, so the normal formatting workflow looked like a failure and required
a second run.

## Possible Solution

## Minimal Reproducible Example

## Context

Two historical observations of the same formatter exit-status behavior, kept in
one report so they share a resolution. Not reproduced as part of this migration.
