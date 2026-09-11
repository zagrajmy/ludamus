---
title: 'Black exception rewriting exposes an interpreter compatibility failure'
severity: 'minor'
context:
  recorded_on: '2026-09-01'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 454
---

## Expected Behavior

## Current Behavior

black 26.5.1 with preview=true rewrites 'except (KeyError, ValueError):' into
Python 2 'except KeyError, ValueError:' in gates/web/django/crowd/auth.py,
producing a file that cannot be imported. Binding the tuple with 'as exc' is
the only form that survives the formatter.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-09-01. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L454).

Historical observation; not reproduced as part of this migration.
