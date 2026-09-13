---
title: 'Testing assertions documentation omits the required status_code argument'
severity: 'minor'
context:
  recorded_on: '2026-09-08'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 517
issue: 'zagrajmy/ludamus#1263'
---

## Expected Behavior

## Current Behavior

MCP test examples in docs/agents/testing-assertions.md omit the required
positional status_code; assert_response(response) fails. Use
assert_response(response, HTTPStatus.OK).

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-08. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L517).

Historical observation; not reproduced as part of this migration.
