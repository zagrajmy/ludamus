---
title: 'Sandbox bootstrap stalls on Go checksums and PyPI metadata'
severity: 'minor'
context:
  recorded_on: '2026-09-01'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 464
---

## Expected Behavior

## Current Behavior

mise run bootstrap in the web sandbox failed on the aliased linter backends
even with MISE_ENV=sandbox: actionlint's go modules died on sum.golang.org
stream errors and shellcheck-py/hadolint-py timed out fetching wheel metadata
from PyPI. Had to build the venv and run poetry, npm and vite by hand to get a
server up.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-01. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L464).

Historical observation; not reproduced as part of this migration.
