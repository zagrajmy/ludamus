---
title: 'Existing e2e seed domain disagrees with the default server environment'
severity: 'minor'
context:
  recorded_on: '2026-09-10'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 557
---

## Expected Behavior

## Current Behavior

PR review browser check: the existing e2e seed uses localhost:8017 but .env.e2e
sets ROOT_DOMAIN=localhost:8000, causing Sphere.DoesNotExist on GET. Match
ROOT_DOMAIN to the isolated server and existing seed rather than modifying the
database.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-10. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L557).

Historical observation; not reproduced as part of this migration.
