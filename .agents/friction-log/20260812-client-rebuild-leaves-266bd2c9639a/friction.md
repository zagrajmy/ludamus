---
title: 'Client rebuild leaves a bare Django server serving deleted asset hashes'
severity: 'minor'
context:
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  occurrences:
    - recorded_on: '2026-08-12'
      source_line: 198
    - recorded_on: '2026-08-20'
      source_line: 300
---

## Expected Behavior

## Current Behavior

### 2026-08-12 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L198)

Ran `vite build` while a hand-started `django runserver` was up, so the running
process kept serving the old hashed CSS filename the build had just deleted.
Pages rendered unstyled and a Playwright hover-opacity assertion failed as if
the CSS were missing — it was a 404. `mise run test:e2e:serve` watches the
manifest and bounces itself; a hand-rolled runserver doesn't, so restart it
after every client build.

### 2026-08-20 — [original note](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L300)

Screenshotting a template change needs the e2e server restarted after 'aubr -C
src/ludamus/client build': django_vite reads the manifest once per process, so
the page silently loads no CSS/JS and every layout measurement is garbage.
test:e2e:serve handles this, a bare 'django runserver' does not.

## Possible Solution

## Minimal Reproducible Example

## Context

Two historical observations of the same process-cached Vite manifest, kept in
one report so they share a resolution. Not reproduced as part of this migration.
