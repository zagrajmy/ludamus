---
title: 'Bootstrap skips incomplete existing development-secret files'
severity: 'minor'
context:
  recorded_on: '2026-07-28'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 107
issue: 'zagrajmy/ludamus#1188'
---

## Expected Behavior

## Current Behavior

Investigated login in the web sandbox: mise run start failed on varlock
validation because the session's .env.local existed but was incomplete, and
bootstrap's `if [ ! -f .env.local ]` guard never repairs an existing file; `rm
.env.local && mise run bootstrap` regenerates it properly.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-28. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L107).

Historical observation; not reproduced as part of this migration.
