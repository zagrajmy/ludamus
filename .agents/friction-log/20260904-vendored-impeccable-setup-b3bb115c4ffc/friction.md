---
title: 'Vendored Impeccable setup imports an absent provider module'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 491
issue: 'zagrajmy/ludamus#1258'
---

## Expected Behavior

## Current Behavior

The impeccable skill's scripts/context.mjs crashes on import:
.claude/skills/impeccable/scripts/lib/provider.mjs is missing from the
checkout, so the skill's setup step cannot run.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L491).

Historical observation; not reproduced as part of this migration.
