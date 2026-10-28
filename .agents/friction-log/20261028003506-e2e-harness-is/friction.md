---
title: 'E2E harness is hard-wired to :8000, so a second checkout cannot run specs'
severity: 'minor'
---

## Expected Behavior

`mise run test:e2e -- tests/x.spec.ts` runs against this checkout's code on a free port when :8000 belongs to another checkout.

## Current Behavior

`test:e2e:prep` refuses when :8000 listens, `test:e2e:serve` binds :8000, and `reuseExistingServer` would silently test whatever else serves :8000.

## Possible Solution

Read the port from `E2E_BASE_URL` in prep/serve and derive `ROOT_DOMAIN`/`POSTHOG_HOST` from it.

## Minimal Reproducible Example

Run any dev server on :8000 from another worktree, then `mise run test:e2e -- tests/proposal-accept.spec.ts` here.

## Context

Had to source `.env.e2e` by hand with `ROOT_DOMAIN=localhost:8020`, replay the prep steps, start runserver myself and pass `E2E_BASE_URL`.
