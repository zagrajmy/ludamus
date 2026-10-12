---
title: 'Firefox setViewportSize hangs for 120s in the sandbox e2e run'
severity: 'minor'
---

## Expected Behavior

`mise run test:e2e` either passes, or fails on a test my branch actually
touches.

## Current Behavior

Two consecutive full runs on a branch that never touches the Konwencik export
each failed one viewport test in `konwencik-export.spec.ts` on firefox with
`page.setViewportSize: Test timeout of 120000ms exceeded` — the call that
resizes the window, not an assertion. The failing width differed between runs
(1440px, then 390px), and a targeted re-run of the spec reproduced it on yet
another width. Chromium and webkit never hit it.

## Possible Solution

Either give firefox a longer action timeout in the Playwright config, or find
what makes a firefox resize block for two minutes under two parallel workers
in this sandbox.

## Minimal Reproducible Example

```
mise run test:e2e:prep
cd tests/e2e && npx playwright test konwencik-export.spec.ts --project=firefox
```

## Context

Cost a targeted per-spec re-run after each of two 17-minute full suites before
I could tell the failure apart from a regression of my own.
