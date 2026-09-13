---
title: 'Artifact-free TypeScript check fails with incremental disabled'
severity: 'minor'
context:
  recorded_on: '2026-09-10'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 554
issue: 'zagrajmy/ludamus#1271'
---

## Expected Behavior

## Current Behavior

PR review: tsc --noEmit --incremental false fails because the client is a
composite project. Use --tsBuildInfoFile pointing into /tmp for a typecheck
without checkout artifacts.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-10. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L554).

Historical observation; not reproduced as part of this migration.
