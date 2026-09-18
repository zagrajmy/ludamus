---
title: 'Playwright flash-message assertions race five-second dismissal'
severity: 'minor'
context:
  recorded_on: '2026-08-12'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 204
issue: 'zagrajmy/ludamus#1205'
---

## Expected Behavior

## Current Behavior

Asserting a flash message in Playwright is a race. Flashes are
`data-flash="transient"` and flash.ts removes them 5s after load, which a slow
local page load can outlast — `expect(getByText("Guild created."))` timed out
while the row it announced was right there. Assert the durable page state
instead.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-12. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L204).

Historical observation; not reproduced as part of this migration.
