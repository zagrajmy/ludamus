---
title: 'E2E-seeded development serves stale built assets without a rebuild workflow'
severity: 'minor'
context:
  recorded_on: '2026-07-25'
  source: 'PAPERCUTS.txt'
  source_commit: '51c7d71cd'
  source_line: 96
issue: 'zagrajmy/ludamus#1186'
---

## Expected Behavior

## Current Behavior

Iterated on timetable CSS/TS against a `.env.e2e` server, where `ENV="test"`
turns django_vite `dev_mode` off, so each edit needed `aubr build` plus a
restart (`--noreload` caches the manifest, and the rebuild deletes the hashed
files it points at - the page then renders with no CSS and reads as a layout
bug). For an edit loop against the e2e seed, export `ENV=development` and
`VITE_PORT`, run the vite dev server, and keep the rest of `.env.e2e`: assets
come from vite with HMR, no build, no restart. Build only before handing the
page to Playwright.

## Possible Solution

## Minimal Reproducible Example

## Context

Originally recorded on 2026-07-25. Imported from [PAPERCUTS.txt](https://github.com/zagrajmy/ludamus/blob/51c7d71cd/PAPERCUTS.txt#L96).

Historical observation; not reproduced as part of this migration.
