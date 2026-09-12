---
title: 'Impeccable task ignores scoped paths and can use an incompatible Python'
severity: 'minor'
context:
  recorded_on: '2026-08-05'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 153
---

## Expected Behavior

## Current Behavior

Scoping impeccable to two templates: 'mise run lint:impeccable
path/to/file.html' silently drops the paths (the task body has no forwarding),
so it scans every tracked HTML/CSS/JS file and looks hung for minutes. That is
the same friction logged on 2026-07-14. Call '.venv/bin/python
scripts/impeccable_lint.py PATH...' to scope it. Use the venv interpreter
specifically: the script uses PEP 758 except syntax at line 102, valid only on
3.14, so a bare 'python' (3.11 on PATH here) raises a SyntaxError that reads
like a repo bug. Black under 3.14 normalizes to that form, so parenthesizing it
fights the formatter and hk reverts the file mid-commit.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-05. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L153).

Historical observation; not reproduced as part of this migration.
