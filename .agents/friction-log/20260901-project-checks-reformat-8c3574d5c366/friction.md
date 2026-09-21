---
title: 'Project checks reformat vendored Impeccable scripts'
severity: 'minor'
context:
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  occurrences:
    - recorded_on: '2026-09-01'
      source_line: 469
    - recorded_on: '2026-09-04'
      source_line: 472
    - recorded_on: '2026-09-04'
      source_line: 499
issue: 'zagrajmy/ludamus#1249'
---

## Expected Behavior

## Current Behavior

### 2026-09-01 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L469)

mise run check reformatted 90 vendored .claude/skills/impeccable/scripts/*.mjs
files unrelated to the diff; had to git checkout -- .claude/ before committing.

### 2026-09-04 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L472)

mise run format (oxfmt) rewrites the vendored
.claude/skills/impeccable/scripts/*.mjs|js files, which are tracked. A one-
file change turned into 90 files of formatter churn I had to stash out before
committing. Those paths should be in the oxfmt ignore list.

### 2026-09-04 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L499)

mise run format:oxfmt globs **/*.mjs with no exclusions, so it restyles the ~90
vendored .claude/skills/impeccable scripts that hk.pkl deliberately excludes.
Ran format, then git add -A, and 31k lines of vendored churn landed in my PR —
enough to push it past CodeRabbit's 100-file review limit. The mise task should
mirror hk.pkl's exclude list.

## Possible Solution

## Minimal Reproducible Example

## Context

Three historical observations of the same formatter-scope defect, kept in one
report so they share a resolution. Not reproduced as part of this migration.
