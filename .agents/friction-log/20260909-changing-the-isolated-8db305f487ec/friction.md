---
title: 'Changing the isolated server port leaves the seeded Site domain stale'
severity: 'minor'
context:
  recorded_on: '2026-09-09'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 548
---

## Expected Behavior

## Current Behavior

Using port 8017 also requires changing the local seeded django_site domain;
ROOT_DOMAIN alone produces Sphere.DoesNotExist. Updated only this worktree’s
disposable SQLite seed.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-09. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L548).

Historical observation; not reproduced as part of this migration.
