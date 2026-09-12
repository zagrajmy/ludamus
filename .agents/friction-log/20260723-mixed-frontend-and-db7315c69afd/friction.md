---
title: 'Mixed frontend and Python checks use incompatible working-directory paths'
severity: 'minor'
context:
  recorded_on: '2026-07-23'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 55
---

## Expected Behavior

## Current Behavior

Ran a mixed JS/Python lint batch from src/ludamus/client while passing
repository-root-relative paths; every path-based check failed. Run mixed checks
from repo root or use paths relative to the chosen workdir.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-23. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L55).

Historical observation; not reproduced as part of this migration.
