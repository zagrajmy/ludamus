---
title: 'Sandbox Python bootstrap has no fallback when the deadsnakes PPA is blocked'
severity: 'minor'
context:
  recorded_on: '2026-08-07'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 162
issue: 'zagrajmy/ludamus#1199'
---

## Expected Behavior

## Current Behavior

docs/agents/sandbox.md documents the python3.14 install as apt+deadsnakes, but
the CC-web egress proxy 403s ppa.launchpadcontent.net, so mise install leaves
no 3.14 and the Python suite can't run. 3.13 is not a fallback — the code
relies on 3.14 PEP 649 deferred annotations (pacts/legacy.py:229 uses
SessionStatus 35 lines before its definition), so imports NameError. I wrongly
concluded the sandbox couldn't run tests at all. `uv python install 3.14`
fetches python-build-standalone from GitHub releases (reachable) in ~4s; worth
making that the documented fallback in the SessionStart hook.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-07. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L162).

Historical observation; not reproduced as part of this migration.
