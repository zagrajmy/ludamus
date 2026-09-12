---
title: 'Agent shell grep function silently skips hidden configuration directories'
severity: 'minor'
context:
  recorded_on: '2026-08-27'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 398
---

## Expected Behavior

## Current Behavior

grep in the agent shell is a shell function that behaves like ripgrep and
silently skips hidden dirs, so 'grep -rn FOO .github/' returns nothing while
the string is really there. Concluded an env var was unset and made a decision
on it; had to re-check with /usr/bin/grep.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-27. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L398).

Historical observation; not reproduced as part of this migration.
