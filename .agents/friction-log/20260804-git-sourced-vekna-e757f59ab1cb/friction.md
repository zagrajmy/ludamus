---
title: 'Git-sourced Vekna mise configuration blocks tasks run inside its checkout'
severity: 'minor'
context:
  recorded_on: '2026-08-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 143
issue: 'zagrajmy/ludamus#1195'
---

## Expected Behavior

## Current Behavior

Running any mise task with cwd inside .venv/src/vekna fails with 'Config files
in .../vekna/mise.toml are not trusted' instead of running the repo task. A
git-sourced Poetry dependency ships its own mise.toml into the venv and mise's
config discovery walks up into it. Needs a 'mise trust' note in
docs/agents/sandbox.md.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L143).

Historical observation; not reproduced as part of this migration.
