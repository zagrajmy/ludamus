---
title: 'Screenshot Chrome fails to launch without a usable sandbox'
severity: 'minor'
context:
  recorded_on: '2026-08-02'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 131
issue: 'zagrajmy/ludamus#1194'
---

## Expected Behavior

## Current Behavior

mise run shots fails on this machine: Chrome aborts with 'No usable sandbox'
before writing DevToolsActivePort. Playwright (test:e2e) launches fine, so the
wrapper needs --no-sandbox or a note pointing at the e2e screenshots instead.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-02. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L131).

Historical observation; not reproduced as part of this migration.
