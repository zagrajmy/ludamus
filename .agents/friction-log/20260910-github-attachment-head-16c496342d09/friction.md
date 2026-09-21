---
title: 'GitHub attachment HEAD verification fails despite working GET downloads'
severity: 'minor'
context:
  recorded_on: '2026-09-10'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 561
issue: 'zagrajmy/ludamus#1273'
---

## Expected Behavior

## Current Behavior

GitHub attachment verification: urllib HEAD followed the new gh --attach asset
redirect to a 403, while curl GET returned both PNGs successfully. Verify
uploaded screenshots with GET, not HEAD.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-10. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L561).

Historical observation; not reproduced as part of this migration.
