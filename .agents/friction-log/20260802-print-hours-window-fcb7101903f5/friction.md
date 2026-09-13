---
title: 'Print hours-window E2E case flakes under worker contention'
severity: 'minor'
context:
  recorded_on: '2026-08-02'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 135
issue: 'zagrajmy/ludamus#1192'
---

## Expected Behavior

## Current Behavior

mise run test:e2e -- tests/print-flow.spec.ts → the existing hours-window case
flaked once under five-worker contention after the new regression case passed;
rerunning the regression alone passed.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-02. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L135).

Historical observation; not reproduced as part of this migration.
