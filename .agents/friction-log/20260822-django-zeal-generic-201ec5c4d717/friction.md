---
title: 'Django-zeal generic foreign-key patch breaks translation-command startup'
severity: 'minor'
context:
  recorded_on: '2026-08-22'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 327
---

## Expected Behavior

## Current Behavior

mise run messages-resolve failed: 'aubr varlock django-admin makemessages'
crashes at django.setup() — zeal.patch.patch_generic_foreign_key does
GenericForeignKey.__get__, which no longer exists in the installed Django.
Worked around by running makemessages with DEBUG=false so settings skip the
zeal app. mise run messages / messages-check hit the same crash.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-22. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L327).

Historical observation; not reproduced as part of this migration.
