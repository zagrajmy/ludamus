---
title: 'E2E prep may relink Playwright dependencies underneath its running test runner'
severity: 'minor'
context:
  recorded_on: '2026-08-16'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 268
issue: 'zagrajmy/ludamus#1212'
---

## Expected Behavior

## Current Behavior

e2e: prep's 'aube install' rewrites node_modules while 'npx playwright test'
(already launched by run_e2e.sh) has resolved its own runner copy. When the
install actually relinks the store, every spec dies with 'Playwright Test did
not expect test.describe() to be called here' plus a bogus global-teardown
coverage error. Whole suite red, zero code cause, passes on the next run.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-16. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L268).

Historical observation; not reproduced as part of this migration.
