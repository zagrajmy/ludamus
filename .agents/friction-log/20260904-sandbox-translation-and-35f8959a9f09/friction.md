---
title: 'Sandbox translation and pre-commit tasks fail on incomplete configuration'
severity: 'minor'
context:
  recorded_on: '2026-09-04'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 507
---

## Expected Behavior

## Current Behavior

Sandbox: 'mise run messages' fails config validation (empty required env var),
so a django.po edit had to be hand-written. djlint in .venv was also missing
its 'regex' and 'pyyaml' deps, which blocked the pre-commit hook until I
pip-installed them by hand.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-04. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L507).

Historical observation; not reproduced as part of this migration.
