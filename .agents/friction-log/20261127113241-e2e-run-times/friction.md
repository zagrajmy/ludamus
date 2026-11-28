---
title: 'E2E run times out while test:e2e:prep is still seeding'
severity: 'minor'
---

## Expected Behavior

`mise run test:e2e -- tests/<name>.spec.ts --project=chromium` starts the server and runs the spec.

## Current Behavior

Playwright stopped after 180 s with "Timed out waiting 180000ms from config.webServer". `test:e2e:prep` was still in `bootstrap_dynamic_fields.py`. Then, with the specs passing, the task still exited non-zero: `coverage report` could not read `src/ludamus/templates/event/parts/_session_participants_panel.html`, a template that no longer exists.

## Possible Solution

Raise the webServer timeout, or document the manual path. Erase the stale e2e coverage data before the report.

## Minimal Reproducible Example

Workaround used: `mise run test:e2e:prep`, then `mise run test:e2e:serve` in the background, then the `test:e2e` command.

## Context

Cost two extra runs while adding tests/e2e/tests/tool-page.spec.ts.
