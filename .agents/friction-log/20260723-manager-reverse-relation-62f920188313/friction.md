---
title: 'Manager reverse relation is sphere_set rather than user.spheres'
severity: 'minor'
context:
  recorded_on: '2026-07-23'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 52
issue: 'zagrajmy/ludamus#1177'
---

## Expected Behavior

## Current Behavior

Checking the seeded manager via user.spheres failed because Sphere.managers
keeps Django's default reverse name; use user.sphere_set or query
Sphere.managers directly.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-23. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L52).

Historical observation; not reproduced as part of this migration.
