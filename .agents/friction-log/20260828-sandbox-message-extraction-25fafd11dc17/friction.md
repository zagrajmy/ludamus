---
title: 'Sandbox message extraction requires secrets and unavailable gettext'
severity: 'minor'
context:
  recorded_on: '2026-08-28'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 422
---

## Expected Behavior

## Current Behavior

Ran mise run messages in the web sandbox to refresh i18n; varlock rejects the
default env (no SECRET_KEY etc.) and even with .env.e2e exported django-admin
makemessages dies on missing gettext (msguniq). No sandbox path to run
extraction.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-28. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L422).

Historical observation; not reproduced as part of this migration.
