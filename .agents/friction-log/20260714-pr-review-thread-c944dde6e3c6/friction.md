---
title: 'PR review-thread helper has an unclear comment output shape'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 28
issue: 'zagrajmy/ludamus#1167'
---

## Expected Behavior

## Current Behavior

Assumed fetched PR review-thread comments were objects with a body field; this
repository helper returned a different shape and made the jq audit fail.
Document the helper output schema or ship a ready unresolved-thread query.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L28).

Historical observation; not reproduced as part of this migration.
