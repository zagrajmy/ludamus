---
title: 'agent-browser Chrome cannot launch in the host sandbox'
severity: 'minor'
context:
  recorded_on: '2026-08-16'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 263
issue: 'zagrajmy/ludamus#1211'
---

## Expected Behavior

## Current Behavior

mise run shots: agent-browser's Chrome dies with 'No usable sandbox' on this
host, and --args "--no-sandbox" passed to 'agent-browser open' does not help;
also a target containing '?' comes through quoted (URL became
http://localhost:8000'/event/x/?view=enrollment'). Fell back to playwright
screenshot.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-16. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L263).

Historical observation; not reproduced as part of this migration.
