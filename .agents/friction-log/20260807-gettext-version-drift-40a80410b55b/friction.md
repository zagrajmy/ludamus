---
title: 'Gettext version drift rewrites catalog format flags and wrapping'
severity: 'minor'
context:
  recorded_on: '2026-08-07'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 171
issue: 'zagrajmy/ludamus#1198'
---

## Expected Behavior

## Current Behavior

mise run messages rewrites the whole PL catalog with this machine's xgettext:
it strips every '#, python-brace-format' flag and rewraps two msgstrs, so CI's
messages-check (which regenerates with a newer gettext and diffs) fails on a
catalog that is locally 'fresh'. Had to hand-revert 11 flag lines and 2
wrappings to get a diff containing only real changes.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-07. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L171).

Historical observation; not reproduced as part of this migration.
