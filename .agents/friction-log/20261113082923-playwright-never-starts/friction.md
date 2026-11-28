---
title: 'Playwright never starts in a web sandbox: the privacy server on :8001 is not seen as ready'
severity: 'minor'
---

## Expected Behavior

`playwright test` starts once both web servers answer.

## Current Behavior

In a Claude Code web sandbox, `aube exec playwright test tests/panel-space-tree.spec.ts` waited 180 s and failed with "Timed out waiting 180000ms from config.webServer". The second webServer (`mise run test:e2e:serve:privacy`, url `http://localhost:8001/`) answers every request with a 302 to `ludamus.localhost:8001`, which the runner's readiness probe does not resolve here, so it never counts as up.

## Possible Solution

Probe a URL that answers 200 without a host redirect, or skip the privacy server unless a privacy spec is selected.

## Minimal Reproducible Example

In a web sandbox: `mise run test:e2e:prep`, then `aube exec -C tests/e2e playwright test tests/panel-space-tree.spec.ts --project=chromium`.

## Context

Worked around it by serving a placeholder on :8001 so `reuseExistingServer` accepted it; privacy specs cannot run that way.
