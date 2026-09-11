---
title: 'Markdownlint autofix turns line-leading issue references into headings'
severity: 'minor'
context:
  recorded_on: '2026-08-12'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 190
---

## Expected Behavior

## Current Behavior

markdownlint's pre-commit autofix rewrites a line that begins with an issue
reference (#834) into '# 834', turning it into an H1 and then failing
MD022/MD025 on its own fix. Had to rewrap the paragraph so no line starts with
'#'.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-12. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L190).

Historical observation; not reproduced as part of this migration.
