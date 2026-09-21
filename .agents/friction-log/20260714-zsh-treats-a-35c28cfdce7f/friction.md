---
title: 'Zsh treats a commit variable followed by a colon as a modifier'
severity: 'minor'
context:
  recorded_on: '2026-07-14'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 25
issue: 'zagrajmy/ludamus#1172'
---

## Expected Behavior

## Current Behavior

Built a screenshot asset commit, then zsh parsed `$asset_commit:refs/...` as a
variable modifier and corrupted the push refspec; brace variables immediately
before colons in zsh.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-14. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L25).

Historical observation; not reproduced as part of this migration.
