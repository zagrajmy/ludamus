---
title: 'E2E environment lacks SUPPORT_EMAIL for message extraction'
severity: 'minor'
context:
  recorded_on: '2026-09-08'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 514
issue: 'zagrajmy/ludamus#1260'
---

## Expected Behavior

## Current Behavior

Konwencik translation extraction: sourcing .env.e2e still failed varlock
validation because SUPPORT_EMAIL is missing; supplied a test address
explicitly.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-08. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L514).

Historical observation; not reproduced as part of this migration.
