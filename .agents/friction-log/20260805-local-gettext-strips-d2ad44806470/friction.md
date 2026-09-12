---
title: 'Local gettext strips format flags retained by CI'
severity: 'minor'
context:
  recorded_on: '2026-08-05'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 148
---

## Expected Behavior

## Current Behavior

mise run messages-check fails locally on 11 pre-existing '#,
python-brace-format' flags: the local xgettext strips them, but main and CI
both keep them. Regenerating the catalog silently drops the flags, so after
'mise run messages' you have to revert the catalog and hand-apply only the real
msgid deltas.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-05. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L148).

Historical observation; not reproduced as part of this migration.
