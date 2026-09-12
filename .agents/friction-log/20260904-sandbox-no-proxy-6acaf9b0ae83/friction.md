---
title: 'Sandbox NO_PROXY sends PyPI installs down a failing direct route'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 504
---

## Expected Behavior

## Current Behavior

uv/poetry installs hung silently in the web sandbox: pypi.org and
files.pythonhosted.org are on the proxy's NO_PROXY list but the direct route
times out; running the bootstrap with NO_PROXY= no_proxy= cleared fixed it

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L504).

Historical observation; not reproduced as part of this migration.
