---
title: 'Migration 0150 fails when its unique index already exists but its history row does not'
severity: 'minor'
context:
  recorded_on: '2026-08-26'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 353
---

## Expected Behavior

## Current Behavior

dev DB drift: migration 0150_track_unique_name_per_event unapplied but its
index already existed; migrate failed until I fake-applied 0150

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-26. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L353).

Historical observation; not reproduced as part of this migration.
