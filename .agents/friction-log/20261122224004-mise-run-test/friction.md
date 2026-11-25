---
title: '`mise run test:e2e` times out because test:e2e:prep takes about 180 s inside Playwright''s webServer'
severity: 'minor'
---

## Expected Behavior

`mise run test:e2e -- tests/panel.spec.ts --project=chromium` starts the server and runs the spec.

## Current Behavior

On a machine with no e2e server running, the webServer command runs `test:e2e:prep` first. Prep took 2m59s here. Playwright's webServer timeout is 180 s, so the run died with "Timed out waiting 180000ms from config.webServer" while `bootstrap_confirmations.py` was still running. No test ran.

## Possible Solution

Raise the webServer timeout, or have `run_e2e.sh` run prep before it starts Playwright.

## Minimal Reproducible Example

`mise run test:e2e:kill && mise run test:e2e -- tests/panel.spec.ts --project=chromium`

## Context

Workaround: run `mise run test:e2e:prep`, then `mise run test:e2e:serve` in the background, then the spec. With that workaround the task still exits non-zero after all tests pass, because the final `coverage report` step has no data from the separately started server.
