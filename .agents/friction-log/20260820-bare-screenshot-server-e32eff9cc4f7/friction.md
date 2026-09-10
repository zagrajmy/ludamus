---
title: 'Bare screenshot server keeps stale Vite manifest entries after rebuilds'
severity: 'minor'
context:
  recorded_on: '2026-08-20'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 300
---

## Expected Behavior

## Current Behavior

Screenshotting a template change needs the e2e server restarted after 'aubr -C
src/ludamus/client build': django_vite reads the manifest once per process, so
the page silently loads no CSS/JS and every layout measurement is garbage.
test:e2e:serve handles this, a bare 'django runserver' does not.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-08-20. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L300).

Historical observation; not reproduced as part of this migration.
